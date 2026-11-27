"""Durable repo KB jobs on the existing surreal-commands worker."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import ConflictError, InvalidInputError
from open_notebook.repo_kb.native_db import (
    config_hash,
    one,
    public_job,
    query,
    record,
    transaction,
)
from open_notebook.repo_kb.native_lock import WriteLock, acquire, release
from open_notebook.repo_kb.native_settings import allowed_roots, data_roots
from open_notebook.repo_kb.native_sync import sync_source


class JobCancelled(Exception):
    pass


async def submit_job(
    db: Any,
    kb_id: RecordID,
    kind: str,
    *,
    source_id: RecordID | None = None,
    options: dict[str, Any] | None = None,
    enqueue: bool = True,
) -> dict[str, Any]:
    await one(db, kb_id, "repo_kb")
    options = options or {}
    lock = await acquire(db.query_raw, kb_id)
    job_id: RecordID | None = None
    try:
        if kind == "sync_batch":
            for value in options.get("source_ids", []):
                item = await one(db, value, "repo_source")
                if item["kb"] != kb_id or not item["enabled"]:
                    raise InvalidInputError("Invalid or disabled source in batch")
                if not item.get("last_commit") and options.get(
                    "confirmed_sources", {}
                ).get(str(item["id"])) != config_hash(item):
                    raise ConflictError(
                        "Source protection rules changed before the batch was queued"
                    )
        if source_id:
            source = await one(db, source_id, "repo_source")
            if source["kb"] != kb_id:
                raise InvalidInputError("Source belongs to another knowledge base")
            if not source.get("last_commit") and (
                not options.get("confirmed")
                or options.get("config_hash") != config_hash(source)
            ):
                raise ConflictError(
                    "Review and confirm the current protection rules before the first sync"
                )
        rows = await transaction(
            db,
            "CREATE repo_kb_job CONTENT $data;",
            {
                "data": {
                    "kb": kb_id,
                    "source": source_id,
                    "kind": kind,
                    "options": options,
                    "lock_token": lock.token,
                    "progress": {"stage": "queued", "done": 0, "total": 0},
                }
            },
            lock,
        )
        job_id = rows[0]["id"]
        await transaction(
            db,
            "UPDATE $lock SET job_id=$job, expires=time::now()+24h;",
            {"job": str(job_id)},
            lock,
        )
        if not enqueue:
            return {"job_id": str(job_id)}
        # Registration and submission are library operations; keep their sync
        # database path off the API event loop.
        from surreal_commands import submit_command

        import commands.repo_kb_commands  # noqa: F401

        command_id = await asyncio.to_thread(
            submit_command, "open_notebook", "repo_kb_job", {"job_id": str(job_id)}
        )
        if not command_id:
            raise RuntimeError("Background worker did not return a command identifier")
        await query(
            db,
            "UPDATE $id SET command_id=$command;",
            {"id": job_id, "command": str(command_id)},
        )
        return {"job_id": str(job_id), "command_id": str(command_id)}
    except Exception:
        if job_id:
            await query(db, "DELETE $id;", {"id": job_id})
        await release(db.query_raw, lock)
        raise


async def cancel_job(db: Any, job_id: RecordID) -> dict[str, Any]:
    job = await one(db, job_id, "repo_kb_job")
    if job["status"] in {"completed", "failed", "cancelled"}:
        return public_job(job)
    await query(db, "UPDATE $id SET cancel_requested=true;", {"id": job_id})
    if job["status"] == "queued":
        await query(
            db,
            "UPDATE $id SET status='cancelled', updated=time::now();",
            {"id": job_id},
        )
        lock = WriteLock(
            RecordID(
                "repo_kb_lock", hashlib.sha256(str(job["kb"]).encode()).hexdigest()
            ),
            job["kb"],
            job["lock_token"],
        )
        await release(db.query_raw, lock)
    return public_job(await one(db, job_id, "repo_kb_job"))


async def execute_job(db: Any, job_id: RecordID) -> dict[str, Any]:
    job = await one(db, job_id, "repo_kb_job")
    if job["status"] in {"completed", "cancelled"}:
        return job.get("result", {})
    lock = WriteLock(
        RecordID("repo_kb_lock", hashlib.sha256(str(job["kb"]).encode()).hexdigest()),
        job["kb"],
        job["lock_token"],
    )

    async def progress(stage: str, done: int = 0, total: int = 0) -> None:
        latest = await one(db, job_id, "repo_kb_job")
        if latest.get("cancel_requested"):
            raise JobCancelled()
        await transaction(
            db,
            "UPDATE $id SET progress=$progress, updated=time::now();",
            {"id": job_id, "progress": {"stage": stage, "done": done, "total": total}},
            lock,
        )

    async def file_progress(done: int, total: int) -> None:
        if done % 100 == 0 or done == total:
            await progress("extract", done, total)

    active_source = None
    try:
        await transaction(
            db,
            "UPDATE $id SET status='running', updated=time::now();",
            {"id": job_id},
            lock,
        )
        await progress("start")
        options = job.get("options", {})
        result: dict[str, Any] = {}
        if job["kind"] in {"sync", "sync_batch"}:
            ids = (
                [job["source"]]
                if job.get("source")
                else [record(s, "repo_source") for s in options.get("source_ids", [])]
            )
            for source_id in ids:
                active_source = source_id
                source = await one(db, source_id, "repo_source")
                if source["kb"] != job["kb"]:
                    raise InvalidInputError("Source scope mismatch")
                await query(
                    db,
                    "UPDATE $id SET status='syncing',last_error=NONE;",
                    {"id": source_id},
                )
                stats = await sync_source(
                    db,
                    source_id,
                    allowed_roots=await allowed_roots(db),
                    data_roots=data_roots(),
                    progress=file_progress,
                    incremental=options.get("mode") != "full"
                    and not source.get("needs_full"),
                    reserved_lock=lock,
                )
                await transaction(
                    db,
                    "UPDATE $id SET by_category=$categories,needs_full=false; CREATE repo_kb_event CONTENT $event;",
                    {
                        "id": source_id,
                        "categories": stats["by_category"],
                        "event": {
                            "kb": job["kb"],
                            "source": source_id,
                            "action": "sync",
                            "detail": stats,
                        },
                    },
                    lock,
                )
                result[str(source_id)] = stats
                active_source = None
            await progress("build")
            from open_notebook.repo_kb.native_wiki import build_wiki

            result["build"] = await build_wiki(db, job["kb"], lock, progress)
        elif job["kind"] == "build":
            from open_notebook.repo_kb.native_wiki import build_wiki

            result = await build_wiki(db, job["kb"], lock, progress)
        elif job["kind"] == "verify":
            from open_notebook.repo_kb.native_verify import verify_exclusions

            result = await verify_exclusions(db, job["kb"])
        elif job["kind"] in {"compile_rules", "compile_flows"}:
            from open_notebook.repo_kb.native_compile import compile_pages

            result = await compile_pages(
                db, job["kb"], lock, job["kind"], options, progress
            )
        elif job["kind"] == "export":
            from open_notebook.repo_kb.native_export import export_git

            result = await export_git(db, job["kb"], lock)
        else:
            raise InvalidInputError("Unknown knowledge base job")
        if job["kind"] in {
            "sync",
            "sync_batch",
            "build",
            "compile_rules",
            "compile_flows",
        }:
            from open_notebook.repo_kb.native_export import export_git

            try:
                result["export"] = await export_git(db, job["kb"], lock)
            except Exception as export_error:
                # The DB canonical copy and completed sync remain usable when
                # an optional Git export fails; show the separate export error.
                result["export"] = {"error": type(export_error).__name__}
                await query(
                    db,
                    "UPDATE repo_wiki_export SET last_error=$error WHERE kb=$kb;",
                    {"kb": job["kb"], "error": type(export_error).__name__},
                )
        await progress("done", 1, 1)
        await transaction(
            db,
            "UPDATE $id SET status='completed', result=$result,updated=time::now();",
            {"id": job_id, "result": result},
            lock,
        )
        return result
    except BaseException as exc:
        state = (
            "cancelled"
            if isinstance(exc, (JobCancelled, asyncio.CancelledError))
            else "failed"
        )
        error = None if state == "cancelled" else type(exc).__name__
        await query(
            db,
            "UPDATE $id SET status=$status,error=$error,updated=time::now();",
            {"id": job_id, "status": state, "error": error},
        )
        if active_source:
            await query(
                db,
                "UPDATE $id SET status='error',last_error=$error;",
                {"id": active_source, "error": error or "cancelled"},
            )
        if state == "cancelled":
            return {"cancelled": True}
        raise RuntimeError("Knowledge base job failed; see its error type") from None
    finally:
        await release(db.query_raw, lock)
