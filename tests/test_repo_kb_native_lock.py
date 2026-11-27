"""A stale job must not write after its knowledge-base lease is replaced."""

from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_lock import KnowledgeBaseBusy, acquire, release
from open_notebook.repo_kb.native_store import create_snapshot


@pytest.mark.asyncio
async def test_exclusive_lease_and_stale_worker_fencing() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_lock", "fencing")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = RecordID("repo_kb", "one")
        source = RecordID("repo_source", "one")
        await db.query("CREATE $id SET name='one', scope='global';", {"id": kb})
        await db.query(
            "CREATE $id SET kb=$kb, name='docs', path='/repo', role='doc';",
            {"id": source, "kb": kb},
        )
        first = await acquire(db.query_raw, kb)
        with pytest.raises(KnowledgeBaseBusy):
            await acquire(db.query_raw, kb)
        await db.query("UPDATE $id SET expires=time::now()-1s;", {"id": first.id})
        second = await acquire(db.query_raw, kb)
        with pytest.raises(RuntimeError):
            await create_snapshot(db.query_raw, source, "commit", first)
        await release(db.query_raw, first)
        assert await create_snapshot(db.query_raw, source, "commit", second)
        await release(db.query_raw, second)
