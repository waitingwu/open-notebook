from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.exceptions import ConflictError, NotFoundError
from open_notebook.repo_kb.native_batches import (
    execute_batch,
    recover_batch,
    submit_batch,
)
from open_notebook.repo_kb.native_catalog import create_kb
from open_notebook.repo_kb.native_db import query, record
from open_notebook.repo_kb.native_jobs import recover_expired_jobs, submit_job
from open_notebook.repo_kb.native_management import (
    delete_kb,
    mounts,
    set_mounts,
    update_kb,
)


@pytest.mark.asyncio
async def test_scope_change_requires_explicit_detach_and_deletion_cleans_mounts():
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_scope", "test")
        await db.query(
            'DEFINE TABLE notebook SCHEMALESS; CREATE notebook:a SET name="A"; CREATE notebook:b SET name="B";'
        )
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = await create_kb(
            db.query, name="Private", owner_notebook=RecordID("notebook", "a")
        )
        other = RecordID("notebook", "b")
        with pytest.raises(NotFoundError):
            await set_mounts(db, other, [str(kb["id"])])
        await update_kb(db, kb["id"], {"scope": "global"}, [])
        assert len(await set_mounts(db, other, [str(kb["id"])])) == 1
        with pytest.raises(ConflictError):
            await update_kb(
                db, kb["id"], {"scope": "notebook", "owner_notebook": "notebook:a"}, []
            )
        assert len(await mounts(db, other)) == 1
        await update_kb(
            db,
            kb["id"],
            {"scope": "notebook", "owner_notebook": "notebook:a"},
            ["notebook:b"],
        )
        assert await mounts(db, other) == []
        await set_mounts(db, RecordID("notebook", "a"), [str(kb["id"])])
        await delete_kb(db, kb["id"])
        assert await mounts(db, RecordID("notebook", "a")) == []
        assert await query(db, "SELECT * FROM repo_kb;") == []


@pytest.mark.asyncio
async def test_batch_global_concurrency_independent_failures_and_cancel(monkeypatch):
    monkeypatch.setattr("surreal_commands.submit_command", lambda *_: "command:batch")

    async def compiler(_db, _kb, _lock, _kind, options, _progress):
        if options["modules"] == ["A0"]:
            raise ValueError("synthetic module failure")
        return {"compiled": 1}

    monkeypatch.setattr("open_notebook.repo_kb.native_compile.compile_pages", compiler)
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_batch", "test")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = await create_kb(db.query, name="Batch")
        items = [{"kb_id": str(kb["id"]), "modules": ["A0", "Q0"]}]
        first = await submit_batch(db, items, None)
        with pytest.raises(ConflictError):
            await submit_batch(db, items, None)
        result = await execute_batch(db, record(first["batch_id"], "repo_kb_batch"))
        assert result == {"completed": 1, "failed": 1, "cancelled": 0}
        second = await submit_batch(db, items, None)
        await query(
            db,
            "UPDATE $id SET cancelled=true;",
            {"id": record(second["batch_id"], "repo_kb_batch")},
        )
        result = await execute_batch(db, record(second["batch_id"], "repo_kb_batch"))
        assert result["cancelled"] == 2


@pytest.mark.asyncio
async def test_expired_worker_is_retryable_without_recovering_live_worker(monkeypatch):
    monkeypatch.setattr("surreal_commands.submit_command", lambda *_: "command:batch")
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_recovery", "test")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = await create_kb(db.query, name="Recovery")
        batch = await submit_batch(
            db, [{"kb_id": str(kb["id"]), "modules": ["A0", "Q0"]}], None
        )
        batch_id = record(batch["batch_id"], "repo_kb_batch")
        job = await submit_job(db, kb["id"], "build", enqueue=False)
        job_id = record(job["job_id"], "repo_kb_job")
        items = batch["items"]
        items[0].update(status="running", job_id=str(job_id))
        await query(
            db,
            "UPDATE $id SET items=$items; UPDATE $job SET status='running',kind='sync_batch'; CREATE repo_source:interrupted SET kb=$kb,name='interrupted',path='/synthetic',role='doc',include=[],exclude=[],protected=[],status='syncing';",
            {"id": batch_id, "items": items, "job": job_id, "kb": kb["id"]},
        )
        await recover_expired_jobs(db, kb["id"])
        assert (await query(db, "SELECT * FROM ONLY $id;", {"id": job_id}))[
            "status"
        ] == "running"
        await query(
            db,
            "UPDATE repo_kb_lock SET expires=time::now()-1s WHERE job_id=$owner;",
            {"owner": str(job_id)},
        )
        await recover_batch(db, batch_id)
        result = await query(db, "SELECT * FROM ONLY $id;", {"id": batch_id})
        assert [i["status"] for i in result["items"]] == ["failed", "cancelled"]
        assert await query(db, "SELECT * FROM repo_kb_lock;") == []
        interrupted = await query(db, "SELECT * FROM ONLY repo_source:interrupted;")
        assert (
            interrupted["status"] == "error"
            and interrupted["last_error"] == "WorkerInterrupted"
        )
        retry = await submit_job(db, kb["id"], "build", enqueue=False)
        assert retry["job_id"] != str(job_id)
