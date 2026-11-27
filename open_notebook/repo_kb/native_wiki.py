"""Build the native deterministic wiki and keyword index from active snapshots."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Awaitable, Callable

from surrealdb import RecordID

from open_notebook.repo_kb.native_access import (
    chunks_for_files,
    current_files,
    reconstruct_text,
)
from open_notebook.repo_kb.native_db import one, query, transaction
from open_notebook.repo_kb.native_lock import WriteLock
from open_notebook.repo_kb.native_pages import save_page
from open_notebook.repo_kb.native_render import Page, render
from open_notebook.repo_kb.native_search_store import (
    build_generation,
    publish_generation,
)

Progress = Callable[[str, int, int], Awaitable[None]]


async def rebuild_search(db: Any, kb: RecordID, lock: WriteLock) -> dict[str, Any]:
    files = await current_files(db, kb)
    documents: list[tuple[RecordID, str]] = []
    for start in range(0, len(files), 250):
        rows = await chunks_for_files(db, files[start : start + 250])
        documents.extend((row["id"], row["body"]) for row in rows)
    rows = (
        await query(
            db, "SELECT id,body FROM repo_wiki_section WHERE kb=$kb;", {"kb": kb}
        )
        or []
    )
    documents.extend((row["id"], row["body"]) for row in rows)

    async def locked(sql: str, params: dict[str, Any]) -> Any:
        return await transaction(db, sql, params, lock)

    generation = await build_generation(locked, kb, documents)
    await publish_generation(locked, kb, generation)
    old = (
        await query(
            db,
            "SELECT id FROM repo_search_generation WHERE kb=$kb AND id!=$current;",
            {"kb": kb, "current": generation},
        )
        or []
    )
    await transaction(
        db,
        "DELETE repo_search_document WHERE $old CONTAINS generation; DELETE repo_search_posting WHERE $old CONTAINS generation; DELETE $old;",
        {"old": [r["id"] for r in old]},
        lock,
    )
    return {"documents": len(documents), "generation": str(generation)}


async def refresh_directory(db: Any, kb: RecordID, lock: WriteLock) -> None:
    knowledge_base = await one(db, kb, "repo_kb")
    sources = (
        await query(
            db, "SELECT * FROM repo_source WHERE kb=$kb AND enabled=true;", {"kb": kb}
        )
        or []
    )
    dependencies = [{"source": str(source["id"])} for source in sources]
    commits = {
        source["name"]: source["last_commit"]
        for source in sources
        if source.get("last_commit")
    }
    entries = (
        await query(
            db,
            "SELECT slug,title,summary,kind,stale FROM repo_wiki_page WHERE kb=$kb;",
            {"kb": kb},
        )
        or []
    )
    directory = [f"# {knowledge_base['name']}", "", "## 知識目錄"]
    for page in sorted(entries, key=lambda r: r["slug"]):
        if (
            page["kind"] != "table"
            and page["slug"] != "index"
            and (page.get("summary") or not page["stale"])
        ):
            directory.append(
                f"- [{page['title']}]({page['slug']}.md)：{page['summary']}"
                + ("（來源已變更，待重新編譯）" if page["stale"] else "")
            )
    directory += ["", "資料表依表名精確對照或到資料表索引查找。"]
    await save_page(
        db,
        kb,
        Page(
            "index",
            "index",
            knowledge_base["name"],
            f"{len(entries)} 頁的分層知識庫目錄。",
            "\n".join(directory),
        ),
        lock,
        dependencies=dependencies,
        source_commits=commits,
        check_citations=False,
    )


async def build_wiki(
    db: Any, kb: RecordID, lock: WriteLock, progress: Progress | None = None
) -> dict[str, Any]:
    knowledge_base = await one(db, kb, "repo_kb")
    files = await current_files(db, kb)
    texts: dict[str, str] = {}
    for start in range(0, len(files), 250):
        batch = files[start : start + 250]
        chunks = await chunks_for_files(db, batch)
        grouped: dict[str, list[dict[str, Any]]] = {}
        for chunk in chunks:
            grouped.setdefault(str(chunk["file"]), []).append(chunk)
        for file in batch:
            texts[str(file["id"])] = reconstruct_text(
                file, grouped.get(str(file["id"]), [])
            )
            file["mirror"] = bool(file["lines"])
            file.setdefault("module", None)
            file.setdefault("last_date", None)
    pages, differences = await asyncio.to_thread(
        render, knowledge_base["name"], files, texts
    )
    sources = (
        await query(
            db, "SELECT * FROM repo_source WHERE kb=$kb AND enabled=true;", {"kb": kb}
        )
        or []
    )
    dependencies = [{"source": str(s["id"])} for s in sources]
    commits = {s["name"]: s["last_commit"] for s in sources if s.get("last_commit")}
    existing = (
        await query(db, "SELECT * FROM repo_wiki_page WHERE kb=$kb;", {"kb": kb}) or []
    )
    for page in existing:
        if page["generated_by"] != "build" and page.get("source_commits") != commits:
            await transaction(
                db, "UPDATE $id SET stale=true;", {"id": page["id"]}, lock
            )
    for i, page in enumerate(pages, 1):
        await save_page(
            db,
            kb,
            page,
            lock,
            dependencies=dependencies,
            source_commits=commits,
            check_citations=False,
        )
        if progress and (i % 100 == 0 or i == len(pages)):
            await progress("build", i, len(pages))
    slugs = {p.slug for p in pages}
    disappeared = [
        p["id"]
        for p in existing
        if p["generated_by"] == "build"
        and p["slug"] not in slugs
        and p["slug"] != "index"
    ]
    await transaction(
        db,
        "UPDATE $ids SET body='',summary='',stale=true; DELETE repo_wiki_section WHERE $ids CONTAINS page;",
        {"ids": disappeared},
        lock,
    )
    await refresh_directory(db, kb, lock)
    # Preserve reviewer decisions by a stable discrepancy fingerprint.
    active_keys = []
    for d in differences:
        key = hashlib.sha256(
            str((d["kind"], d["module"], d["program"], d["detail"])).encode()
        ).hexdigest()
        active_keys.append(key)
        target = RecordID(
            "repo_discrepancy", hashlib.sha256((str(kb) + key).encode()).hexdigest()
        )
        before = await query(db, "SELECT * FROM ONLY $id;", {"id": target})
        refs = [r for r in d["evidence"] if r]
        data = {
            "kb": kb,
            "module": d["module"] or "",
            "program": d["program"] or "",
            "kind": d["kind"],
            "fingerprint": key,
            "summary": d["detail"],
            "spec_cite": refs[0] if refs else None,
            "code_cite": refs[1] if len(refs) > 1 else None,
            "status": before.get("status", "open")
            if isinstance(before, dict)
            else "open",
            "note": before.get("note") if isinstance(before, dict) else None,
        }
        await transaction(
            db, "UPSERT $id CONTENT $data;", {"id": target, "data": data}, lock
        )
    await transaction(
        db,
        "DELETE repo_discrepancy WHERE kb=$kb AND NOT ($keys CONTAINS fingerprint);",
        {"kb": kb, "keys": active_keys},
        lock,
    )
    if progress:
        await progress("index", 0, 1)
    index = await rebuild_search(db, kb, lock)
    await transaction(
        db,
        "UPDATE $kb SET stale=false,last_build_at=time::now(),last_build_commit_set=$commits;",
        {"kb": kb, "commits": commits},
        lock,
    )
    from open_notebook.repo_kb.native_content import health

    report = await health(db, kb, lock)
    return {
        "pages": len(pages) + 1,
        "discrepancies": len(set(active_keys)),
        "index": index,
        "health": report,
    }
