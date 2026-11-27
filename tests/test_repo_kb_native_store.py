"""File replacement stays atomic and never duplicates stale chunks."""

from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_ingest import PreparedChunk, PreparedFile
from open_notebook.repo_kb.native_store import (
    activate_snapshot,
    create_snapshot,
    file_id,
    replace_file,
)


@pytest.mark.asyncio
async def test_replace_file_replaces_chunks_and_preserves_other_files() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_native_store", "replace")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        source = RecordID("repo_source", "test")
        snapshot = await create_snapshot(db.query_raw, source, "testcommit")
        prepared = PreparedFile(
            "a.txt", "blob1", "sop", None, "text", 1, {}, [PreparedChunk(1, 1, "first")]
        )
        await replace_file(db.query_raw, source, snapshot, prepared)
        updated = PreparedFile(
            "a.txt",
            "blob2",
            "sop",
            None,
            "text",
            1,
            {},
            [PreparedChunk(1, 1, "second")],
        )
        await replace_file(db.query_raw, source, snapshot, updated)
        chunks = await db.query(
            "SELECT body FROM repo_chunk WHERE file = $id;",
            {"id": file_id(source, snapshot, "a.txt")},
        )
        assert chunks == [{"body": "second"}]
        row = await db.query(
            "SELECT * FROM ONLY $id;", {"id": file_id(source, snapshot, "a.txt")}
        )
        assert row["blob"] == "blob2"
        assert row["last_commit"] == "testcommit"
        invalid = PreparedFile(
            "a.txt",
            "bad",
            "sop",
            None,
            "text",
            1,
            {},
            [PreparedChunk(1, 1, None)],  # type: ignore[arg-type]
        )
        with pytest.raises(Exception):
            await replace_file(db.query_raw, source, snapshot, invalid)
        chunks = await db.query(
            "SELECT body FROM repo_chunk WHERE file = $id;",
            {"id": file_id(source, snapshot, "a.txt")},
        )
        assert chunks == [{"body": "second"}]
        row = await db.query(
            "SELECT * FROM ONLY $id;", {"id": file_id(source, snapshot, "a.txt")}
        )
        assert row["blob"] == "blob2"
        empty = PreparedFile("a.txt", "blob3", "other", None, "unsupported", 0, {}, [])
        await replace_file(db.query_raw, source, snapshot, empty)
        assert await db.query("SELECT * FROM repo_chunk;") == []


@pytest.mark.asyncio
async def test_snapshot_switch_preserves_previous_on_failed_activation() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_native_store", "snapshot")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = RecordID("repo_kb", "test")
        source = RecordID("repo_source", "test")
        await db.query("CREATE $id SET name='test', scope='global';", {"id": kb})
        await db.query(
            "CREATE $id SET kb=$kb, name='docs', path='/repo', role='doc';",
            {"id": source, "kb": kb},
        )
        first = await create_snapshot(db.query_raw, source, "commit1")
        prepared = PreparedFile(
            "a.txt", "blob", "sop", None, "text", 1, {}, [PreparedChunk(1, 1, "first")]
        )
        await replace_file(db.query_raw, source, first, prepared)
        await activate_snapshot(db.query_raw, source, first, kb, "commit1", 1)
        with pytest.raises(RuntimeError):
            await replace_file(db.query_raw, source, first, prepared)
        second = await create_snapshot(db.query_raw, source, "commit2")
        with pytest.raises(RuntimeError):
            await activate_snapshot(db.query_raw, source, second, kb, "incorrect", 2)
        with pytest.raises(RuntimeError):
            await activate_snapshot(db.query_raw, source, second, kb, "commit2", 2)
        row = await db.query("SELECT * FROM ONLY $id;", {"id": source})
        assert row["current_snapshot"] == first
        assert row["last_commit"] == "commit1"
