"""Exercise the native repo KB schema on an isolated SurrealDB."""

from typing import Any

import pytest
from surrealdb import AsyncSurreal

from open_notebook.database.async_migrate import AsyncMigrationManager


@pytest.mark.asyncio
async def test_repo_kb_migration_defaults_and_rollback() -> None:
    manager = AsyncMigrationManager()
    up, down = manager.up_migrations[29], manager.down_migrations[29]
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_migration", "defaults")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(up.sql)
        await db.query("CREATE repo_kb:test SET name='test', scope='global';")
        source = await db.query(
            "CREATE repo_source:test SET kb=repo_kb:test, "
            "name='docs', path='/example', role='doc';"
        )
        assert source[0]["protected"] == []
        assert source[0]["enabled"] is True
        page = await db.query(
            "CREATE repo_wiki_page:test SET kb=repo_kb:test, slug='index', "
            "kind='index', title='Index', body='', content_hash='hash', "
            "generated_by='build';"
        )
        assert page[0]["citations"] == []
        assert page[0]["summary"] == ""
        await db.query(down.sql)
        info = await db.query("INFO FOR DB;")
        assert "repo_kb" not in info["tables"]
        assert "repo_source" not in info["tables"]
