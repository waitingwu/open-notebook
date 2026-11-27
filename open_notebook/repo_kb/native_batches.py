"""Persistent sequential compilation batches with independent module outcomes."""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from surrealdb import RecordID

from open_notebook.exceptions import ConflictError, InvalidInputError
from open_notebook.repo_kb.native_db import one, query, record
from open_notebook.repo_kb.native_jobs import (
    execute_job,
    recover_expired_jobs,
    submit_job,
)


async def recover_batch(db: Any, batch_id: RecordID) -> None:
    """Release a batch whose active worker lost its fenced write lease."""
    batch = await one(db, batch_id, "repo_kb_batch")
    interrupted = False
    items = batch["items"]
    for item in items:
        if item["status"] != "running" or not item.get("job_id"):
            continue
        await recover_expired_jobs(db, record(item["kb_id"], "repo_kb"))
        job = await one(db, item["job_id"], "repo_kb_job")
        if job["status"] == "failed" and job.get("error") == "WorkerInterrupted":
            item.update(status="failed", error="WorkerInterrupted")
            interrupted = True
    if interrupted:
        for item in items:
            if item["status"] == "queued":
                item["status"] = "cancelled"
        await query(
            db,
            "UPDATE $id SET items=$items,cancelled=true;",
            {"id": batch_id, "items": items},
        )
        await query(
            db,
            "DELETE repo_kb_lock:compiler WHERE token=$owner;",
            {"owner": str(batch_id)},
        )


async def submit_batch(
    db: Any, items: list[dict[str, Any]], model_id: str | None
) -> dict[str, Any]:
    expanded = []
    for item in items:
        kb = record(item["kb_id"], "repo_kb")
        await one(db, kb, "repo_kb")
        for kind, key in (("compile_rules", "modules"), ("compile_flows", "flows")):
            for value in dict.fromkeys(item.get(key, [])):
                expanded.append(
                    {
                        "kb_id": str(kb),
                        "kind": kind,
                        "value": value,
                        "model_id": model_id,
                        "status": "queued",
                    }
                )
    if not expanded:
        raise InvalidInputError("Select at least one module or flow")
    batch = RecordID("repo_kb_batch", uuid4().hex)
    # All worker processes share this lease: independent batches cannot spend
    # AI quota concurrently. Source-sync jobs keep their per-KB concurrency.
    try:
        await query(
            db,
            """BEGIN TRANSACTION;
        LET $current = SELECT * FROM ONLY repo_kb_lock:compiler;
        IF $current != NONE AND $current.expires > time::now() { THROW 'Compilation batch already active'; };
        UPSERT repo_kb_lock:compiler CONTENT {kb:$kb,token:$batch_lease,job_id:$batch_lease,expires:time::now()+24h};
        CREATE $id SET items=$items;
        COMMIT TRANSACTION;""",
            {
                "id": batch,
                "items": expanded,
                "kb": record(expanded[0]["kb_id"], "repo_kb"),
                "batch_lease": str(batch),
            },
        )
    except RuntimeError as exc:
        raise ConflictError(
            "Another compilation batch is active; inspect or cancel it first"
        ) from exc
    from surreal_commands import submit_command

    import commands.repo_kb_commands  # noqa: F401

    try:
        await asyncio.to_thread(
            submit_command, "open_notebook", "repo_kb_batch", {"batch_id": str(batch)}
        )
    except Exception:
        await query(db, "DELETE $id;", {"id": batch})
        await query(
            db,
            "DELETE repo_kb_lock:compiler WHERE token=$batch_lease;",
            {"batch_lease": str(batch)},
        )
        raise
    return {"batch_id": str(batch), "items": expanded}


async def execute_batch(db: Any, batch_id: RecordID) -> dict[str, int]:
    try:
        return await _execute_batch(db, batch_id)
    finally:
        await query(
            db,
            "DELETE repo_kb_lock:compiler WHERE token=$batch_lease;",
            {"batch_lease": str(batch_id)},
        )


async def _execute_batch(db: Any, batch_id: RecordID) -> dict[str, int]:
    batch = await one(db, batch_id, "repo_kb_batch")
    items = batch["items"]
    for index, item in enumerate(items):
        if item["status"] in {"completed", "failed", "cancelled"}:
            continue
        latest = await one(db, batch_id, "repo_kb_batch")
        if latest["cancelled"]:
            item["status"] = "cancelled"
        else:
            lease = await query(
                db,
                "UPDATE repo_kb_lock:compiler SET expires=time::now()+24h WHERE token=$batch_lease RETURN AFTER;",
                {"batch_lease": str(batch_id)},
            )
            if not lease:
                raise ConflictError("Compilation batch lease was lost")
            item["status"] = "running"
            await query(
                db, "UPDATE $id SET items=$items;", {"id": batch_id, "items": items}
            )
            try:
                key = "modules" if item["kind"] == "compile_rules" else "flows"
                job = await submit_job(
                    db,
                    record(item["kb_id"], "repo_kb"),
                    item["kind"],
                    options={key: [item["value"]], "model_id": item.get("model_id")},
                    enqueue=False,
                )
                item["job_id"] = job["job_id"]
                await query(
                    db, "UPDATE $id SET items=$items;", {"id": batch_id, "items": items}
                )
                await execute_job(db, record(job["job_id"], "repo_kb_job"))
                outcome = await one(db, job["job_id"], "repo_kb_job")
                item["status"] = outcome["status"]
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = type(exc).__name__
        items[index] = item
        await query(
            db, "UPDATE $id SET items=$items;", {"id": batch_id, "items": items}
        )
    return {
        state: sum(i["status"] == state for i in items)
        for state in ("completed", "failed", "cancelled")
    }
