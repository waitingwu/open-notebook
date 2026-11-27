"""File replacement stays atomic and never duplicates stale chunks."""

from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_ingest import PreparedChunk, PreparedFile
from open_notebook.repo_kb.native_store import file_id, replace_file


@pytest.mark.asyncio
async def test_replace_file_replaces_chunks_and_preserves_other_files() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_native_store", "replace")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        source = RecordID("repo_source", "test")
        prepared = PreparedFile(
            "a.txt", "blob1", "sop", None, "text", 1, {}, [PreparedChunk(1, 1, "first")]
        )
        await replace_file(db.query_raw, source, prepared)
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
        await replace_file(db.query_raw, source, updated)
        chunks = await db.query(
            "SELECT body FROM repo_chunk WHERE file = $id;",
            {"id": file_id(source, "a.txt")},
        )
        assert chunks == [{"body": "second"}]
        row = await db.query(
            "SELECT * FROM ONLY $id;", {"id": file_id(source, "a.txt")}
        )
        assert row["blob"] == "blob2"
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
            await replace_file(db.query_raw, source, invalid)
        chunks = await db.query(
            "SELECT body FROM repo_chunk WHERE file = $id;",
            {"id": file_id(source, "a.txt")},
        )
        assert chunks == [{"body": "second"}]
        row = await db.query(
            "SELECT * FROM ONLY $id;", {"id": file_id(source, "a.txt")}
        )
        assert row["blob"] == "blob2"
        empty = PreparedFile("a.txt", "blob3", "other", None, "unsupported", 0, {}, [])
        await replace_file(db.query_raw, source, empty)
        assert await db.query("SELECT * FROM repo_chunk;") == []
