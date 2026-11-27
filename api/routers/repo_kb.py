"""Native repo knowledge-base management, jobs, and content endpoints."""

from __future__ import annotations

import asyncio
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from open_notebook.database.repository import db_connection, parse_record_ids
from open_notebook.exceptions import (
    ConfigurationError,
    ConflictError,
    OpenNotebookError,
)
from open_notebook.repo_kb import native_catalog, native_content
from open_notebook.repo_kb.native_cite import resolve
from open_notebook.repo_kb.native_db import (
    config_hash,
    one,
    public_job,
    query,
    record,
    transaction,
    visible_kb,
)
from open_notebook.repo_kb.native_jobs import (
    cancel_job,
    recover_expired_jobs,
    submit_job,
)
from open_notebook.repo_kb.native_lock import acquire, release
from open_notebook.repo_kb.native_lookup import search
from open_notebook.repo_kb.native_mutations import (
    delete_source,
    parse_rules,
    update_protected,
)
from open_notebook.repo_kb.native_paths import validate_source_path
from open_notebook.repo_kb.native_preview import browse, preview
from open_notebook.repo_kb.native_settings import allowed_roots, data_roots, settings
from open_notebook.repo_kb.native_verify import verify_exclusions

router = APIRouter(prefix="/repo-kb")


async def database() -> AsyncIterator[Any]:
    try:
        async with db_connection() as db:
            yield db
    except OpenNotebookError:
        raise
    except (ValueError, OSError) as exc:
        raise ConfigurationError(
            "Invalid repository or knowledge base configuration"
        ) from exc
    except Exception as exc:
        raise OpenNotebookError("Knowledge base operation failed") from exc


def public_source(row: dict[str, Any]) -> dict[str, Any]:
    return {**parse_record_ids(row), "config_hash": config_hash(row)}


class KBCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    scope: Literal["global", "notebook"] = "global"
    owner_notebook: str | None = None


class SourceCreate(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9_-]{1,32}$")
    path: str = Field(min_length=1, max_length=4096)
    role: Literal["doc", "src"]
    include: list[str] = Field(default_factory=lambda: ["**"], max_length=100)
    exclude: list[str] = Field(default_factory=list, max_length=100)
    protected: list[dict[str, Any]] | None = Field(default=None, max_length=100)


class SourcePatch(BaseModel):
    name: str | None = Field(default=None, pattern=r"^[a-z0-9_-]{1,32}$")
    path: str | None = Field(default=None, min_length=1, max_length=4096)
    role: Literal["doc", "src"] | None = None
    include: list[str] | None = None
    exclude: list[str] | None = None
    enabled: bool | None = None


class ProtectedUpdate(BaseModel):
    rules: list[dict[str, Any]] = Field(max_length=100)
    confirm_patterns: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=2000)


class SyncRequest(BaseModel):
    mode: Literal["auto", "full"] = "auto"
    confirmed: bool = False
    config_hash: str | None = None


class SyncBatchRequest(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=100)
    confirmed_sources: dict[str, str] = Field(default_factory=dict)
    mode: Literal["auto", "full"] = "auto"


@router.post("/sources/sync-batch")
async def sync_many(body: SyncBatchRequest, db: Any = Depends(database)) -> Any:
    groups: dict[str, list[str]] = {}
    for value in dict.fromkeys(body.source_ids):
        source = await one(db, value, "repo_source")
        if not source.get("last_commit") and body.confirmed_sources.get(
            str(source["id"])
        ) != config_hash(source):
            raise ConflictError(
                "Review all source protection rules before the first sync"
            )
        groups.setdefault(str(source["kb"]), []).append(str(source["id"]))
    results: list[dict[str, Any]] = []
    for kb, ids in groups.items():
        result = await submit_job(
            db,
            record(kb, "repo_kb"),
            "sync_batch",
            options={
                "source_ids": ids,
                "mode": body.mode,
                "confirmed_sources": body.confirmed_sources,
            },
        )
        results.extend({"source_id": value, **result} for value in ids)
    return {"jobs": results}


class SettingsUpdate(BaseModel):
    default_protected: list[dict[str, Any]] = Field(default_factory=list)
    allowed_roots: list[str] = Field(default_factory=list)
    selector_timeout: int = Field(default=20, ge=1, le=120)
    confirm_patterns: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=2000)


@router.get("/kbs")
async def list_kbs(notebook_id: str | None = None, db: Any = Depends(database)) -> Any:
    rows = await query(db, "SELECT * FROM repo_kb ORDER BY name;") or []
    sources = (
        await query(db, "SELECT kb,file_count,last_synced_at FROM repo_source;") or []
    )
    differences = (
        await query(db, "SELECT kb FROM repo_discrepancy WHERE status='open';") or []
    )
    for row in rows:
        members = [s for s in sources if s["kb"] == row["id"]]
        row.update(
            {
                "source_count": len(members),
                "file_count": sum(s["file_count"] for s in members),
                "open_discrepancies": sum(d["kb"] == row["id"] for d in differences),
                "last_synced_at": max(
                    (s["last_synced_at"] for s in members if s.get("last_synced_at")),
                    default=None,
                ),
            }
        )
    if notebook_id:
        notebook = record(notebook_id, "notebook")
        rows = [
            r
            for r in rows
            if r["scope"] == "global" or r.get("owner_notebook") == notebook
        ]
    return parse_record_ids(rows)


@router.post("/kbs")
async def add_kb(body: KBCreate, db: Any = Depends(database)) -> Any:
    if body.scope == "notebook" and not body.owner_notebook:
        raise ConfigurationError("Choose the notebook that owns this knowledge base")
    row = await native_catalog.create_kb(
        db.query,
        name=body.name,
        description=body.description,
        owner_notebook=record(body.owner_notebook, "notebook")
        if body.scope == "notebook" and body.owner_notebook
        else None,
    )
    return parse_record_ids(row)


@router.get("/kbs/{kb_id}")
async def get_kb(
    kb_id: str, notebook_id: str | None = None, db: Any = Depends(database)
) -> Any:
    return parse_record_ids(await visible_kb(db, kb_id, notebook_id))


class KBPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    scope: Literal["global", "notebook"] | None = None
    owner_notebook: str | None = None
    detach_confirmed: list[str] = Field(default_factory=list)


@router.get("/kbs/{kb_id}/mounted-notebooks")
async def mounted_notebooks(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    return parse_record_ids(
        await query(
            db,
            "SELECT id,name FROM notebook WHERE repo_kbs CONTAINS $kb;",
            {"kb": kb["id"]},
        )
        or []
    )


@router.patch("/kbs/{kb_id}")
async def edit_kb(kb_id: str, body: KBPatch, db: Any = Depends(database)) -> Any:
    from open_notebook.repo_kb.native_management import update_kb

    return parse_record_ids(
        await update_kb(
            db, record(kb_id, "repo_kb"), body.model_dump(), body.detach_confirmed
        )
    )


@router.delete("/kbs/{kb_id}")
async def remove_kb(
    kb_id: str, confirmed: bool = False, db: Any = Depends(database)
) -> Any:
    from open_notebook.repo_kb.native_management import delete_kb

    if not confirmed:
        raise ConflictError("Confirm knowledge base deletion")
    await delete_kb(db, record(kb_id, "repo_kb"))
    return {"deleted": True}


class MountUpdate(BaseModel):
    kb_ids: list[str] = Field(max_length=8)


@router.get("/notebooks/{notebook_id}/mounts")
async def notebook_mounts(notebook_id: str, db: Any = Depends(database)) -> Any:
    from open_notebook.repo_kb.native_management import mounts

    return parse_record_ids(await mounts(db, record(notebook_id, "notebook")))


@router.get("/notebooks/{notebook_id}/cite")
async def notebook_citation(
    notebook_id: str, ref: str = Query(max_length=8192), db: Any = Depends(database)
) -> Any:
    from open_notebook.repo_kb.native_management import mounts

    for kb in await mounts(db, record(notebook_id, "notebook")):
        result = await resolve(db, kb["id"], ref)
        if result["valid"]:
            return result
    return {"valid": False, "status": "not_in_mounted_knowledge_bases", "ref": ref}


@router.put("/notebooks/{notebook_id}/mounts")
async def save_mounts(
    notebook_id: str, body: MountUpdate, db: Any = Depends(database)
) -> Any:
    from open_notebook.repo_kb.native_management import set_mounts

    return parse_record_ids(
        await set_mounts(db, record(notebook_id, "notebook"), body.kb_ids)
    )


class SaveAnswerRequest(BaseModel):
    session_id: str
    message_id: str
    title: str = Field(min_length=1, max_length=160)


@router.post("/kbs/{kb_id}/qa-pages")
async def save_qa(
    kb_id: str, body: SaveAnswerRequest, db: Any = Depends(database)
) -> Any:
    from open_notebook.repo_kb.native_qa import save_answer

    return await save_answer(
        db, record(kb_id, "repo_kb"), body.session_id, body.message_id, body.title
    )


@router.delete("/kbs/{kb_id}/chats")
async def delete_related_chats(
    kb_id: str, confirmed: bool = False, db: Any = Depends(database)
) -> Any:
    if not confirmed:
        raise ConflictError("Confirm deleting all chats that used this knowledge base")
    from open_notebook.graphs.chat import memory

    kb = await visible_kb(db, kb_id)
    sessions = (
        await query(
            db,
            "SELECT id FROM chat_session WHERE repo_kbs CONTAINS $kb;",
            {"kb": kb["id"]},
        )
        or []
    )
    for session in sessions:
        await asyncio.to_thread(memory.delete_thread, str(session["id"]))
    ids = [s["id"] for s in sessions]
    await query(
        db,
        "DELETE refers_to WHERE $sessions CONTAINS in; DELETE $sessions;",
        {"sessions": ids},
    )
    return {"deleted": len(ids)}


@router.get("/kbs/{kb_id}/sources")
async def list_sources(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    rows = (
        await query(
            db,
            "SELECT * FROM repo_source WHERE kb=$kb ORDER BY name;",
            {"kb": kb["id"]},
        )
        or []
    )
    return [public_source(row) for row in rows]


@router.post("/kbs/{kb_id}/sources")
async def add_source(
    kb_id: str, body: SourceCreate, db: Any = Depends(database)
) -> Any:
    kb = await visible_kb(db, kb_id)
    values = (
        body.protected
        if body.protected is not None
        else (await settings(db))["default_protected"]
    )
    rules = parse_rules(values)
    row = await native_catalog.create_source(
        db.query,
        kb=kb["id"],
        name=body.name,
        path=body.path,
        role=body.role,
        include=body.include,
        exclude=body.exclude,
        protected=rules,
        allowed_roots=await allowed_roots(db),
        data_roots=data_roots(),
    )
    return public_source(row)


@router.patch("/sources/{source_id}")
async def edit_source(
    source_id: str, body: SourcePatch, db: Any = Depends(database)
) -> Any:
    source = await one(db, source_id, "repo_source")
    lock = await acquire(db.query_raw, source["kb"])
    try:
        source = await one(db, source_id, "repo_source")
        changes = body.model_dump(exclude_none=True)
        if "path" in changes:
            changes["path"] = str(
                await asyncio.to_thread(
                    validate_source_path,
                    changes["path"],
                    allowed_roots=await allowed_roots(db),
                    data_roots=data_roots(),
                )
            )
        reset = any(key in changes for key in ("path", "role", "include", "exclude"))
        if reset:
            changes.update({"needs_full": True, "status": "never"})
        await transaction(
            db,
            "UPDATE $id MERGE $data; UPDATE $kb SET stale=true,policy_version=policy_version+1; UPDATE $kb UNSET search_generation;",
            {"id": source["id"], "kb": source["kb"], "data": changes},
            lock,
        )
        if "path" in changes or "role" in changes:
            await transaction(
                db,
                "UPDATE $id UNSET current_snapshot,last_commit;",
                {"id": source["id"]},
                lock,
            )
    finally:
        await release(db.query_raw, lock)
    return public_source(await one(db, source_id, "repo_source"))


@router.delete("/sources/{source_id}")
async def remove_source(
    source_id: str, confirmed: bool = False, db: Any = Depends(database)
) -> Any:
    if not confirmed:
        raise ConflictError("Confirm source deletion")
    await delete_source(db, record(source_id, "repo_source"))
    return {"deleted": True}


@router.post("/sources/{source_id}/preview")
async def preview_source(source_id: str, db: Any = Depends(database)) -> Any:
    source = await one(db, source_id, "repo_source")
    return await preview(source, await allowed_roots(db), data_roots())


@router.post("/sources/preview")
async def preview_unsaved(body: SourceCreate, db: Any = Depends(database)) -> Any:
    values = body.model_dump()
    values["protected"] = (
        body.protected
        if body.protected is not None
        else (await settings(db))["default_protected"]
    )
    parse_rules(values["protected"])
    return await preview(values, await allowed_roots(db), data_roots())


@router.post("/sources/{source_id}/sync")
async def sync_repo(
    source_id: str, body: SyncRequest, db: Any = Depends(database)
) -> Any:
    source = await one(db, source_id, "repo_source")
    return await submit_job(
        db, source["kb"], "sync", source_id=source["id"], options=body.model_dump()
    )


@router.get("/sources/{source_id}/protected")
async def get_protected(source_id: str, db: Any = Depends(database)) -> Any:
    source = await one(db, source_id, "repo_source")
    return {"rules": source.get("protected", [])}


@router.put("/sources/{source_id}/protected")
async def set_protected(
    source_id: str, body: ProtectedUpdate, db: Any = Depends(database)
) -> Any:
    result: dict[str, Any] = dict(
        await update_protected(
            db,
            record(source_id, "repo_source"),
            body.rules,
            confirmations=body.confirm_patterns,
            reason=body.reason,
        )
    )
    source = await one(db, source_id, "repo_source")
    result["build"] = await submit_job(db, source["kb"], "build")
    return result


@router.get("/settings/repo-kb")
async def read_settings(db: Any = Depends(database)) -> Any:
    value = await settings(db)
    return {
        **parse_record_ids(value),
        "effective_allowed_roots": await allowed_roots(db),
        "externally_bound": os.environ.get("API_HOST", "127.0.0.1")
        not in {"localhost", "127.0.0.1", "::1"},
    }


@router.put("/settings/repo-kb")
async def save_settings(body: SettingsUpdate, db: Any = Depends(database)) -> Any:
    rules = parse_rules(body.default_protected)
    previous = await settings(db)
    old = parse_rules(previous["default_protected"])
    remaining = {(r.kind, r.pattern.casefold()): r for r in rules}
    removed = [
        r.pattern
        for r in old
        if (r.kind, r.pattern.casefold()) not in remaining
        or (r.enabled and not remaining[(r.kind, r.pattern.casefold())].enabled)
    ]
    if removed and (
        not body.reason.strip() or not set(removed).issubset(body.confirm_patterns)
    ):
        raise ConflictError(
            "Confirm each removed default protection and provide a reason"
        )
    roots = []
    for value in body.allowed_roots:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ConfigurationError("Allowed roots must be directories")
        roots.append(str(path))
    data = {
        **body.model_dump(exclude={"confirm_patterns", "reason"}),
        "default_protected": [asdict(r) for r in rules],
        "allowed_roots": roots,
    }
    await query(
        db,
        "BEGIN TRANSACTION; UPSERT open_notebook:repo_kb_settings MERGE $data; CREATE repo_exclusion_audit CONTENT $audit; COMMIT TRANSACTION;",
        {
            "data": data,
            "audit": {
                "action": "edit",
                "before": {"rules": previous["default_protected"]},
                "after": {"rules": data["default_protected"]},
                "reason": body.reason or None,
            },
        },
    )
    return data


class ApplyDefaults(BaseModel):
    source_ids: list[str] = Field(min_length=1, max_length=100)
    confirm_patterns: list[str] = Field(default_factory=list)
    reason: str = ""


@router.post("/settings/repo-kb/apply-defaults")
async def apply_defaults(body: ApplyDefaults, db: Any = Depends(database)) -> Any:
    values = (await settings(db))["default_protected"]
    results = []
    kbs = set()
    for source_id in body.source_ids:
        stats = await update_protected(
            db,
            record(source_id, "repo_source"),
            values,
            confirmations=body.confirm_patterns,
            reason=body.reason,
        )
        results.append({"source_id": source_id, **stats})
        kbs.add(str((await one(db, source_id, "repo_source"))["kb"]))
    builds = [await submit_job(db, record(kb, "repo_kb"), "build") for kb in kbs]
    return {"results": results, "builds": builds}


@router.get("/fs/browse")
async def browse_folders(path: str | None = None, db: Any = Depends(database)) -> Any:
    roots = await allowed_roots(db)
    return await browse(
        db, path or (roots[0] if roots else str(Path.home())), roots, data_roots()
    )


@router.get("/kbs/{kb_id}/jobs")
async def jobs(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    await recover_expired_jobs(db, kb["id"])
    rows = (
        await query(
            db,
            "SELECT * FROM repo_kb_job WHERE kb=$kb ORDER BY created DESC LIMIT 20;",
            {"kb": kb["id"]},
        )
        or []
    )
    return parse_record_ids([public_job(row) for row in rows])


@router.get("/jobs/{job_id}")
async def job(job_id: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(public_job(await one(db, job_id, "repo_kb_job")))


@router.delete("/jobs/{job_id}")
async def cancel(job_id: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(await cancel_job(db, record(job_id, "repo_kb_job")))


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, db: Any = Depends(database)) -> Any:
    previous = await one(db, job_id, "repo_kb_job")
    if previous["status"] not in {"failed", "cancelled"}:
        raise ConflictError("Only failed or cancelled jobs can be retried")
    return await submit_job(
        db,
        previous["kb"],
        previous["kind"],
        source_id=previous.get("source"),
        options=previous.get("options", {}),
    )


@router.get("/kbs/{kb_id}/verify-exclusions")
async def verify(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    return await verify_exclusions(db, kb["id"])


@router.post("/kbs/{kb_id}/build")
async def build(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    return await submit_job(db, kb["id"], "build")


class CompileRequest(BaseModel):
    modules: list[str] = Field(default_factory=list, max_length=100)
    flows: list[str] = Field(default_factory=list, max_length=12)
    model_id: str | None = None


@router.post("/kbs/{kb_id}/compile-rules")
async def compile_rules(
    kb_id: str, body: CompileRequest, db: Any = Depends(database)
) -> Any:
    kb = await visible_kb(db, kb_id)
    return await submit_job(db, kb["id"], "compile_rules", options=body.model_dump())


@router.post("/kbs/{kb_id}/compile-flows")
async def compile_flows(
    kb_id: str, body: CompileRequest, db: Any = Depends(database)
) -> Any:
    from open_notebook.repo_kb.native_compile import propose_flows

    kb = await visible_kb(db, kb_id)
    if not body.flows:
        return await propose_flows(db, kb["id"], body.model_id)
    return await submit_job(db, kb["id"], "compile_flows", options=body.model_dump())


@router.get("/rules/stale")
async def stale_rules(db: Any = Depends(database)) -> Any:
    from open_notebook.repo_kb.native_compile import stale_modules

    return parse_record_ids(await stale_modules(db))


class BatchItem(BaseModel):
    kb_id: str
    modules: list[str] = Field(default_factory=list, max_length=100)
    flows: list[str] = Field(default_factory=list, max_length=12)


class CompileBatchRequest(BaseModel):
    items: list[BatchItem] = Field(min_length=1, max_length=100)
    model_id: str | None = None


@router.post("/rules/compile-batch")
async def compile_batch(body: CompileBatchRequest, db: Any = Depends(database)) -> Any:
    from open_notebook.repo_kb.native_batches import submit_batch

    return await submit_batch(db, [i.model_dump() for i in body.items], body.model_id)


@router.get("/rules/batches/{batch_id}")
async def get_batch(batch_id: str, db: Any = Depends(database)) -> Any:
    from open_notebook.repo_kb.native_batches import recover_batch

    await recover_batch(db, record(batch_id, "repo_kb_batch"))
    row = await one(db, batch_id, "repo_kb_batch")
    row["counts"] = {
        state: sum(i["status"] == state for i in row["items"])
        for state in ("queued", "running", "completed", "failed", "cancelled")
    }
    return parse_record_ids(row)


@router.delete("/rules/batches/{batch_id}")
async def cancel_batch(batch_id: str, db: Any = Depends(database)) -> Any:
    row = await one(db, batch_id, "repo_kb_batch")
    await query(db, "UPDATE $id SET cancelled=true;", {"id": row["id"]})
    return {"cancelled": True}


@router.get("/kbs/{kb_id}/export.zip")
async def download_wiki(kb_id: str, db: Any = Depends(database)) -> Response:
    from open_notebook.repo_kb.native_export import export_zip

    data = await export_zip(db, record(kb_id, "repo_kb"))
    return Response(
        data,
        media_type="application/zip",
        headers={
            "Content-Disposition": 'attachment; filename="wiki.zip"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/kbs/{kb_id}/export")
async def export_config(kb_id: str, db: Any = Depends(database)) -> Any:
    kb = await visible_kb(db, kb_id)
    rows = (
        await query(
            db, "SELECT * FROM repo_wiki_export WHERE kb=$kb;", {"kb": kb["id"]}
        )
        or []
    )
    return parse_record_ids(
        rows[0]
        if rows
        else {"enabled": False, "repo_path": "", "branch": "wiki", "subdir": "wiki"}
    )


class ExportUpdate(BaseModel):
    repo_path: str = Field(max_length=4096)
    branch: str = Field(default="wiki", max_length=160)
    subdir: str = Field(default="wiki", max_length=512)
    enabled: bool = False


@router.put("/kbs/{kb_id}/export")
async def save_export(
    kb_id: str, body: ExportUpdate, db: Any = Depends(database)
) -> Any:
    import hashlib

    from surrealdb import RecordID

    from open_notebook.repo_kb.native_export import validate_config

    kb = await visible_kb(db, kb_id)
    path = await validate_config(db, body.repo_path, body.branch, body.subdir)
    lock = await acquire(db.query_raw, kb["id"])
    try:
        await transaction(
            db,
            "UPSERT $id MERGE $data;",
            {
                "id": RecordID(
                    "repo_wiki_export",
                    hashlib.sha256(str(kb["id"]).encode()).hexdigest(),
                ),
                "data": {**body.model_dump(), "repo_path": path, "kb": kb["id"]},
            },
            lock,
        )
    finally:
        await release(db.query_raw, lock)
    return await export_config(kb_id, db)


@router.post("/kbs/{kb_id}/export/run")
async def run_export(kb_id: str, db: Any = Depends(database)) -> Any:
    return await submit_job(db, record(kb_id, "repo_kb"), "export")


@router.get("/kbs/{kb_id}/tree")
async def wiki_tree(kb_id: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(await native_content.tree(db, record(kb_id, "repo_kb")))


@router.get("/kbs/{kb_id}/search")
async def wiki_search(
    kb_id: str,
    q: str = Query(min_length=1, max_length=2000),
    category: str | None = None,
    module: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    db: Any = Depends(database),
) -> Any:
    return await search(
        db, record(kb_id, "repo_kb"), q, category=category, module=module, limit=limit
    )


@router.get("/kbs/{kb_id}/cite")
async def citation(
    kb_id: str, ref: str = Query(max_length=8192), db: Any = Depends(database)
) -> Any:
    return await resolve(db, record(kb_id, "repo_kb"), ref)


@router.get("/kbs/{kb_id}/discrepancies")
async def discrepancies(
    kb_id: str,
    module: str | None = None,
    status: str | None = None,
    db: Any = Depends(database),
) -> Any:
    kb = await visible_kb(db, kb_id)
    rows = (
        await query(
            db, "SELECT * FROM repo_discrepancy WHERE kb=$kb;", {"kb": kb["id"]}
        )
        or []
    )
    return parse_record_ids(
        [
            r
            for r in rows
            if (not module or r["module"] == module)
            and (not status or r["status"] == status)
        ]
    )


class DiscrepancyUpdate(BaseModel):
    status: Literal["open", "confirmed", "dismissed"]
    note: str = Field(default="", max_length=4000)


@router.patch("/kbs/{kb_id}/discrepancies/{discrepancy_id}")
async def mark_discrepancy(
    kb_id: str,
    discrepancy_id: str,
    body: DiscrepancyUpdate,
    db: Any = Depends(database),
) -> Any:
    from open_notebook.exceptions import NotFoundError
    from open_notebook.repo_kb.mask import mask_text

    row = await one(db, discrepancy_id, "repo_discrepancy")
    if row["kb"] != record(kb_id, "repo_kb"):
        raise NotFoundError("Discrepancy not found")
    lock = await acquire(db.query_raw, row["kb"])
    try:
        await transaction(
            db,
            "UPDATE $id MERGE $data;",
            {
                "id": row["id"],
                "data": {"status": body.status, "note": mask_text(body.note)[0]},
            },
            lock,
        )
    finally:
        await release(db.query_raw, lock)
    return parse_record_ids(await one(db, discrepancy_id, "repo_discrepancy"))


@router.get("/sources/{source_id}/protected/audit")
async def exclusion_audit(source_id: str, db: Any = Depends(database)) -> Any:
    source = await one(db, source_id, "repo_source")
    return parse_record_ids(
        await query(
            db,
            "SELECT * FROM repo_exclusion_audit WHERE source=$source ORDER BY ts DESC LIMIT 100;",
            {"source": source["id"]},
        )
        or []
    )


# Suffix routes must precede the catch-all page route.
@router.get("/kbs/{kb_id}/pages/{slug:path}/revisions/{revision}")
async def wiki_revision(
    kb_id: str, slug: str, revision: int, db: Any = Depends(database)
) -> Any:
    return parse_record_ids(
        await native_content.revisions(db, record(kb_id, "repo_kb"), slug, revision)
    )


@router.get("/kbs/{kb_id}/pages/{slug:path}/revisions")
async def wiki_revisions(kb_id: str, slug: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(
        await native_content.revisions(db, record(kb_id, "repo_kb"), slug)
    )


class RestoreRequest(BaseModel):
    revision: int = Field(ge=1)


@router.post("/kbs/{kb_id}/pages/{slug:path}/restore")
async def restore_page(
    kb_id: str, slug: str, body: RestoreRequest, db: Any = Depends(database)
) -> Any:
    kb = record(kb_id, "repo_kb")
    lock = await acquire(db.query_raw, kb)
    try:
        return await native_content.restore(db, kb, slug, body.revision, lock)
    finally:
        await release(db.query_raw, lock)


class NoteRequest(BaseModel):
    body: str = Field(min_length=1, max_length=100000)
    anchor_heading: str | None = None


@router.get("/kbs/{kb_id}/pages/{slug:path}/notes")
async def page_notes(kb_id: str, slug: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(
        (await native_content.page(db, record(kb_id, "repo_kb"), slug))["notes"]
    )


@router.post("/kbs/{kb_id}/pages/{slug:path}/notes")
async def add_note(
    kb_id: str, slug: str, body: NoteRequest, db: Any = Depends(database)
) -> Any:
    kb = record(kb_id, "repo_kb")
    lock = await acquire(db.query_raw, kb)
    try:
        return await native_content.save_note(
            db, kb, slug, body.body, body.anchor_heading, lock
        )
    finally:
        await release(db.query_raw, lock)


@router.patch("/kbs/{kb_id}/pages/{slug:path}/notes/{note_id}")
async def edit_note(
    kb_id: str, slug: str, note_id: str, body: NoteRequest, db: Any = Depends(database)
) -> Any:
    kb = record(kb_id, "repo_kb")
    lock = await acquire(db.query_raw, kb)
    try:
        return await native_content.save_note(
            db,
            kb,
            slug,
            body.body,
            body.anchor_heading,
            lock,
            record(note_id, "repo_wiki_note"),
        )
    finally:
        await release(db.query_raw, lock)


@router.delete("/kbs/{kb_id}/pages/{slug:path}/notes/{note_id}")
async def delete_note(
    kb_id: str, slug: str, note_id: str, db: Any = Depends(database)
) -> Any:
    kb = record(kb_id, "repo_kb")
    lock = await acquire(db.query_raw, kb)
    try:
        return await native_content.save_note(
            db, kb, slug, "", None, lock, record(note_id, "repo_wiki_note"), delete=True
        )
    finally:
        await release(db.query_raw, lock)


@router.get("/kbs/{kb_id}/pages/{slug:path}")
async def wiki_page(kb_id: str, slug: str, db: Any = Depends(database)) -> Any:
    return parse_record_ids(
        await native_content.page(db, record(kb_id, "repo_kb"), slug)
    )
