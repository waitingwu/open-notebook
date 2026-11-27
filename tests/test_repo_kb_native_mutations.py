from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.exceptions import ConflictError
from open_notebook.repo_kb.native_mutations import update_protected
from open_notebook.repo_kb.native_search_store import (
    build_generation,
    publish_generation,
)


@pytest.mark.asyncio
async def test_protection_purges_all_snapshots_and_derived_content() -> None:
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_mutations", "purge")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = RecordID("repo_kb", "one")
        source = RecordID("repo_source", "one")
        await db.query("CREATE $kb SET name='one',scope='global';", {"kb": kb})
        await db.query(
            "CREATE $s SET kb=$kb,name='docs',path='/repo',role='doc';",
            {"s": source, "kb": kb},
        )
        for n in (1, 2):
            await db.query(
                "CREATE repo_file CONTENT $data;",
                {
                    "data": {
                        "source": source,
                        "snapshot": RecordID("repo_source_snapshot", str(n)),
                        "path": "private/a.txt",
                        "blob": "abc",
                        "category": "other",
                        "method": "text",
                    }
                },
            )
        files = await db.query("SELECT * FROM repo_file;")
        for f in files:
            await db.query(
                "CREATE repo_chunk CONTENT $data;",
                {
                    "data": {
                        "source": source,
                        "file": f["id"],
                        "snapshot": f["snapshot"],
                        "path": f["path"],
                        "category": "other",
                        "start_line": 1,
                        "end_line": 1,
                        "body": "sensitive masked text",
                    }
                },
            )
        chunks = await db.query("SELECT * FROM repo_chunk;")
        gen = await build_generation(
            db.query, kb, [(c["id"], c["body"]) for c in chunks]
        )
        await publish_generation(db.query, kb, gen)
        page = RecordID("repo_wiki_page", "one")
        await db.query(
            "CREATE $id CONTENT $data;",
            {
                "id": page,
                "data": {
                    "kb": kb,
                    "slug": "rules/one",
                    "kind": "rule",
                    "title": "one",
                    "body": "secret 〔docs:private/a.txt#L1@abcd〕",
                    "summary": "private",
                    "content_hash": "abc",
                    "generated_by": "compile-rules",
                    "dependencies": [{"source": str(source), "path": "private/a.txt"}],
                },
            },
        )
        revision_result = await db.query(
            "CREATE repo_wiki_revision CONTENT $data;",
            {
                "data": {
                    "page": page,
                    "revision": 1,
                    "body": "private",
                    "summary": "private",
                    "generated_by": "compile-rules",
                }
            },
        )
        assert isinstance(revision_result, list) and len(revision_result) == 1, (
            revision_result
        )
        selected = await db.query(
            "SELECT id FROM repo_wiki_revision WHERE $pages CONTAINS page;",
            {"pages": [page]},
        )
        assert len(selected) == 1, selected
        result = await update_protected(
            db,
            source,
            [{"kind": "dir_name", "pattern": "private", "enabled": True}],
            confirmations=[],
            reason="",
        )
        assert result["files_purged"] == 2
        assert result["pages_invalidated"] == 1
        assert result["revisions_purged"] == 1
        assert await db.query("SELECT * FROM repo_chunk;") == []
        assert await db.query("SELECT * FROM repo_search_posting;") == []
        assert await db.query("SELECT * FROM repo_wiki_revision;") == []
        current = await db.query("SELECT * FROM ONLY $id;", {"id": page})
        assert current["body"] == ""
        assert current["stale"] is True
        with pytest.raises(ConflictError):
            await update_protected(db, source, [], confirmations=[], reason="")
        await update_protected(
            db, source, [], confirmations=["private"], reason="synthetic test"
        )
        source_row = await db.query("SELECT * FROM ONLY $id;", {"id": source})
        assert source_row["protected"] == []
