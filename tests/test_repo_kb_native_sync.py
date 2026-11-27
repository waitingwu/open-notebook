"""A failed full sync leaves the previous snapshot active."""

import subprocess
from pathlib import Path
from typing import Any

import pytest
from surrealdb import AsyncSurreal

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.repo_kb.native_catalog import create_kb, create_source
from open_notebook.repo_kb.native_sync import sync_full_source
from open_notebook.repo_kb.protected_rules import ProtectedRule


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.mark.asyncio
async def test_full_sync_masks_prunes_and_preserves_previous_snapshot_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.name", "Test")
    git(repo, "config", "user.email", "test@example.invalid")
    (repo / "public.txt").write_text("password: hidden-value\n")
    (repo / "secret").mkdir()
    (repo / "secret" / "private.txt").write_text("excluded")
    git(repo, "add", ".")
    git(repo, "commit", "-qm", "initial")
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_native", "sync")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        kb = await create_kb(db.query, name="test")
        source = await create_source(
            db.query,
            kb=kb["id"],
            name="docs",
            path=str(repo),
            role="doc",
            include=["**"],
            exclude=[],
            protected=[ProtectedRule("dir_name", "secret")],
            allowed_roots=[str(tmp_path)],
            data_roots=[],
        )
        result = await sync_full_source(
            db, source["id"], allowed_roots=[str(tmp_path)], data_roots=[]
        )
        assert result["files"] == 1
        current = await db.query("SELECT * FROM ONLY $id;", {"id": source["id"]})
        old_snapshot = current["current_snapshot"]
        chunks = await db.query(
            "SELECT * FROM repo_chunk WHERE snapshot = $snapshot;",
            {"snapshot": old_snapshot},
        )
        assert len(chunks) == 1
        assert "hidden-value" not in chunks[0]["body"]
        assert "<SECRET>" in chunks[0]["body"]
        assert "secret/" not in chunks[0]["path"]
        (repo / "public.txt").write_text("new content")
        git(repo, "add", ".")
        git(repo, "commit", "-qm", "update")

        def fail(*args: Any, **kwargs: Any) -> None:
            raise RuntimeError("fixture extraction failure")

        monkeypatch.setattr("open_notebook.repo_kb.native_sync.prepare_entry", fail)
        with pytest.raises(RuntimeError):
            await sync_full_source(
                db, source["id"], allowed_roots=[str(tmp_path)], data_roots=[]
            )
        current = await db.query("SELECT * FROM ONLY $id;", {"id": source["id"]})
        assert current["current_snapshot"] == old_snapshot
        assert current["last_commit"] == result["commit"]
