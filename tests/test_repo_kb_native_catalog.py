"""Native catalog persists the user's explicitly chosen scope and rules."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from surrealdb import AsyncSurreal, RecordID

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_catalog import create_kb, create_source
from open_notebook.repo_kb.protected_rules import ProtectedRule


@pytest.mark.asyncio
async def test_create_notebook_scoped_kb_and_source(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_catalog", "create")
        await db.query("DEFINE TABLE notebook SCHEMAFULL; CREATE notebook:test;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = await create_kb(
            db.query, name="Example", owner_notebook=RecordID("notebook", "test")
        )
        assert kb["scope"] == "notebook"
        source = await create_source(
            db.query,
            kb=kb["id"],
            name="docs",
            path=str(repo),
            role="doc",
            include=["**"],
            exclude=[],
            protected=[ProtectedRule("dir_name", "secret", note="Private documents")],
            allowed_roots=[str(tmp_path)],
            data_roots=[],
        )
        assert source["protected"] == [
            {
                "kind": "dir_name",
                "pattern": "secret",
                "enabled": True,
                "note": "Private documents",
            }
        ]
        assert source["file_count"] == 0
        with pytest.raises(ValueError):
            await create_kb(
                db.query, name="Example", owner_notebook=RecordID("notebook", "missing")
            )
