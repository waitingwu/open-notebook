"""Building an index does not expose it until the generation is published."""

from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_search import candidates, posting_id
from open_notebook.repo_kb.native_search_store import (
    build_generation,
    candidate_targets,
    invalidate_generation,
    publish_generation,
)


@pytest.mark.asyncio
async def test_build_publish_and_invalidate_index_generation() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_search", "generation")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = RecordID("repo_kb", "one")
        await db.query("CREATE $id SET name='one', scope='global';", {"id": kb})
        generation = await build_generation(
            db.query, kb, [(RecordID("repo_chunk", "one"), "執行紀錄位置")]
        )
        before = await db.query("SELECT * FROM ONLY $id;", {"id": kb})
        assert before.get("search_generation") is None
        assert await candidate_targets(db.query, kb, "執行") == []
        posting = await db.query(
            "SELECT * FROM ONLY $id;", {"id": posting_id(generation, "執行")}
        )
        assert candidates("執行", {"執行": posting["ids"]}, 1) == {0}
        await publish_generation(db.query, kb, generation)
        after = await db.query("SELECT * FROM ONLY $id;", {"id": kb})
        assert after["search_generation"] == generation
        assert await candidate_targets(db.query, kb, "執行紀錄") == [
            RecordID("repo_chunk", "one")
        ]
        await invalidate_generation(db.query, kb)
        after = await db.query("SELECT * FROM ONLY $id;", {"id": kb})
        assert after.get("search_generation") is None
        assert await candidate_targets(db.query, kb, "執行") == []


@pytest.mark.asyncio
async def test_incomplete_generation_cannot_be_published() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_search", "incomplete")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = RecordID("repo_kb", "one")
        await db.query("CREATE $id SET name='one', scope='global';", {"id": kb})
        incomplete = RecordID("repo_search_generation", "incomplete")
        await db.query("CREATE $id SET kb=$kb;", {"id": incomplete, "kb": kb})
        with pytest.raises(ValueError):
            await publish_generation(db.query, kb, incomplete)
        row = await db.query("SELECT * FROM ONLY $id;", {"id": kb})
        assert row.get("search_generation") is None
