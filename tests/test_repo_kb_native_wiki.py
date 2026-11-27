import subprocess
from pathlib import Path
from typing import Any

import pytest
from langchain_core.messages import AIMessage
from surrealdb import AsyncSurreal

from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.exceptions import ConfigurationError
from open_notebook.repo_kb.native_catalog import create_kb, create_source
from open_notebook.repo_kb.native_cite import resolve, validate
from open_notebook.repo_kb.native_content import restore, revisions, save_note
from open_notebook.repo_kb.native_export import _commit, export_zip, validate_config
from open_notebook.repo_kb.native_lock import acquire, release
from open_notebook.repo_kb.native_lookup import search
from open_notebook.repo_kb.native_pages import get_page, save_page
from open_notebook.repo_kb.native_render import Page
from open_notebook.repo_kb.native_sync import sync_source
from open_notebook.repo_kb.native_wiki import build_wiki
from open_notebook.repo_kb.retrieve import retrieve


@pytest.mark.asyncio
async def test_native_wiki_build_citations_history_and_notes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "table.sql").write_text(
        "CREATE TABLE DTTEST (ID INTEGER NOT NULL, PRIMARY KEY (ID));\n"
    )
    (repo / "操作手冊.txt").write_text("執行紀錄位置\nDB2 SQLCODE=-803\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_wiki", "native")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        await db.query(AsyncMigrationManager().up_migrations[30].sql)
        kb = await create_kb(db.query, name="Example")
        source = await create_source(
            db.query,
            kb=kb["id"],
            name="docs",
            path=str(repo),
            role="doc",
            include=["**"],
            exclude=[],
            protected=[],
            allowed_roots=[str(tmp_path)],
            data_roots=[],
        )
        await sync_source(
            db, source["id"], allowed_roots=[str(tmp_path)], data_roots=[]
        )
        lock = await acquire(db.query_raw, kb["id"])
        try:
            result = await build_wiki(db, kb["id"], lock)
            assert result["pages"] >= 4
            page = await get_page(db, kb["id"], "tables/DTTEST")
            assert "ID" in page["body"]
            assert page["revision"] == 1
            reference = page["citations"][0]["ref"]
            citation = await resolve(db, kb["id"], reference)
            assert citation["valid"] is True
            malformed = await validate(
                db, kb["id"], reference + " 〔docs:missing#L1@not-a-commit〕"
            )
            assert malformed["total"] == 2 and len(malformed["invalid"]) == 1
            for keyword in ("執行紀錄位置", "SQLCODE=-803", "DTTEST"):
                hits = await search(db, kb["id"], keyword)
                assert hits, keyword
                for hit in hits:
                    if hit.get("ref"):
                        assert (await resolve(db, kb["id"], hit["ref"]))["valid"]
            await db.query(
                "CREATE repo_wiki_note CONTENT $data;",
                {
                    "data": {
                        "kb": kb["id"],
                        "page": page["id"],
                        "body": "Manual observation",
                    }
                },
            )
            await build_wiki(db, kb["id"], lock)
            page = await get_page(db, kb["id"], "tables/DTTEST")
            assert page["revision"] == 2
            notes = await db.query("SELECT * FROM repo_wiki_note;")
            assert notes[0]["body"] == "Manual observation"
            await save_note(
                db, kb["id"], "tables/DTTEST", "持續保留的人工補充", None, lock
            )
            assert len(await revisions(db, kb["id"], "tables/DTTEST")) == 2
            archive = await export_zip(db, kb["id"])
            assert archive.startswith(b"PK")
            with pytest.raises(ConfigurationError):
                await validate_config(db, str(repo), "wiki", "wiki")
            export = tmp_path / "export"
            export.mkdir()
            subprocess.run(["git", "init", "-q", str(export)], check=True)
            subprocess.run(
                ["git", "-C", str(export), "config", "user.name", "Test"], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(export),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            commit = _commit(
                str(export),
                "wiki",
                "wiki",
                {"Example/index.md": b"# Wiki"},
                "Test export",
            )
            assert len(commit) == 40
            assert not (export / "wiki").exists()  # no working-tree checkout
            assert (
                subprocess.check_output(
                    ["git", "-C", str(export), "show", "wiki:wiki/Example/index.md"]
                )
                == b"# Wiki"
            )

            class Fake:
                async def ainvoke(self, *_args, **_kwargs):
                    return AIMessage(content='{"pages":["outside/current-kb"]}')

            retrieved = await retrieve(db, kb["id"], "DTTEST", model=Fake())
            assert "tables/DTTEST" in retrieved["metrics"]["entities"]
            assert retrieved["metrics"]["fallback"] == "ValueError"
            assert reference in retrieved["context"]
            source_row = await db.query("SELECT * FROM ONLY $id;", {"id": source["id"]})
            first = "# Rule\n第一版 " + reference
            second = "# Rule\n第二版 " + reference
            for body in (first, second):
                await save_page(
                    db,
                    kb["id"],
                    Page("rules/A0", "rule", "A0", "規則摘要", body, "A0"),
                    lock,
                    generated_by="compile-rules",
                    model="fixture-model",
                    dependencies=[{"source": str(source["id"])}],
                    source_commits={"docs": source_row["last_commit"]},
                )
            assert len(await revisions(db, kb["id"], "rules/A0")) == 2
            await restore(db, kb["id"], "rules/A0", 1, lock)
            restored = await get_page(db, kb["id"], "rules/A0")
            assert restored["revision"] == 3 and restored["body"] == first
            assert not restored["stale"]
            (repo / "操作手冊.txt").write_text("執行紀錄位置已更新\n")
            subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
            subprocess.run(
                ["git", "-C", str(repo), "commit", "-qm", "update SOP"], check=True
            )
            await sync_source(
                db,
                source["id"],
                allowed_roots=[str(tmp_path)],
                data_roots=[],
                reserved_lock=lock,
            )
            await build_wiki(db, kb["id"], lock)
            assert (await get_page(db, kb["id"], "rules/A0"))["stale"]
            await restore(db, kb["id"], "rules/A0", 1, lock)
            assert (await get_page(db, kb["id"], "rules/A0"))["stale"]
        finally:
            await release(db.query_raw, lock)
