"""Wiki browsing, revisions, manual notes, and health from the DB canonical copy."""

from __future__ import annotations

import posixpath
import re
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.repo_kb.mask import mask_text
from open_notebook.repo_kb.native_access import check_policy_version, current_files
from open_notebook.repo_kb.native_cite import citations, validate
from open_notebook.repo_kb.native_db import query, transaction, visible_kb
from open_notebook.repo_kb.native_lock import WriteLock
from open_notebook.repo_kb.native_pages import (
    get_page,
    page_readable,
    save_page,
    sections,
)
from open_notebook.repo_kb.native_render import Page


async def page(db: Any, kb: RecordID, slug: str) -> dict[str, Any]:
    base = await visible_kb(db, kb)
    row = await get_page(db, kb, slug)
    if not await page_readable(db, kb, row):
        raise NotFoundError("Wiki page is no longer available under the current policy")
    row["notes"] = (
        await query(
            db,
            "SELECT * FROM repo_wiki_note WHERE page=$page ORDER BY created;",
            {"page": row["id"]},
        )
        or []
    )
    await check_policy_version(db, kb, base.get("policy_version", 0))
    return row


async def tree(db: Any, kb: RecordID) -> dict[str, Any]:
    base = await visible_kb(db, kb)
    rows = (
        await query(
            db,
            "SELECT id,slug,kind,title,summary,module,stale,revision,dependencies FROM repo_wiki_page WHERE kb=$kb ORDER BY slug;",
            {"kb": kb},
        )
        or []
    )
    rows = [row for row in rows if await page_readable(db, kb, row)]
    for row in rows:
        row.pop("dependencies", None)
    files = await current_files(db, kb)
    modules: dict[str, dict[str, int]] = {}
    for file in files:
        counts = modules.setdefault(file.get("module") or "other", {})
        counts[file["category"]] = counts.get(file["category"], 0) + 1
    await check_policy_version(db, kb, base.get("policy_version", 0))
    return {"pages": rows, "modules": modules, "health": base.get("health", {})}


async def revisions(
    db: Any, kb: RecordID, slug: str, revision: int | None = None
) -> Any:
    base = await visible_kb(db, kb)
    current = await page(db, kb, slug)
    rows = (
        await query(
            db,
            "SELECT * FROM repo_wiki_revision WHERE page=$page ORDER BY revision DESC;",
            {"page": current["id"]},
        )
        or []
    )
    rows = [
        r
        for r in rows
        if (revision is None or r["revision"] == revision)
        and await page_readable(db, kb, r)
    ]
    await check_policy_version(db, kb, base.get("policy_version", 0))
    if revision is not None:
        if not rows:
            raise NotFoundError("Wiki revision not found")
        return rows[0]
    return [
        {k: v for k, v in r.items() if k not in {"body", "dependencies"}} for r in rows
    ]


async def restore(
    db: Any, kb: RecordID, slug: str, version: int, lock: WriteLock
) -> dict[str, Any]:
    current = await page(db, kb, slug)
    if current["generated_by"] == "build":
        raise InvalidInputError("Deterministic pages must be rebuilt from sources")
    old = await revisions(db, kb, slug, version)
    result = await save_page(
        db,
        kb,
        Page(
            slug,
            current["kind"],
            current["title"],
            old["summary"],
            old["body"],
            current.get("module"),
        ),
        lock,
        generated_by=old["generated_by"],
        model=old.get("model"),
        dependencies=old.get("dependencies", []),
        source_commits=old.get("source_commits", {}),
    )
    from open_notebook.repo_kb.native_wiki import rebuild_search

    await rebuild_search(db, kb, lock)
    return result


async def save_note(
    db: Any,
    kb: RecordID,
    slug: str,
    body: str,
    anchor: str | None,
    lock: WriteLock,
    note: RecordID | None = None,
    delete: bool = False,
) -> dict[str, Any]:
    current = await page(db, kb, slug)
    body = mask_text(body)[0]
    if not delete and not body.strip():
        raise InvalidInputError("A manual note cannot be empty")
    if anchor and anchor not in {
        p["heading"] for p in sections(current["id"], kb, current["body"])
    }:
        raise InvalidInputError("The heading no longer exists")
    report = await validate(db, kb, body)
    if report["invalid"]:
        raise InvalidInputError("Manual note has invalid citations")
    target = note or RecordID("repo_wiki_note", __import__("uuid").uuid4().hex)
    if note and not any(n["id"] == target for n in current["notes"]):
        raise NotFoundError("Manual note not found")
    data = {
        "kb": kb,
        "page": current["id"],
        "body": body,
        "anchor_heading": anchor,
        "citations": citations(body),
        "dependencies": current.get("dependencies", []),
        "stale": False,
    }
    sql = (
        "DELETE $id;"
        if delete
        else "UPSERT $id MERGE $data; UPDATE $id SET updated=time::now();"
    )
    await transaction(db, sql, {"id": target, "data": data}, lock)
    notes = (
        await query(
            db,
            "SELECT body FROM repo_wiki_note WHERE page=$page;",
            {"page": current["id"]},
        )
        or []
    )
    values = sections(
        current["id"],
        kb,
        current["body"] + "\n\n" + "\n\n".join(n["body"] for n in notes),
    )
    await transaction(
        db,
        "DELETE repo_wiki_section WHERE page=$page; INSERT INTO repo_wiki_section $sections RETURN NONE;",
        {"page": current["id"], "sections": values},
        lock,
    )
    from open_notebook.repo_kb.native_wiki import rebuild_search

    await rebuild_search(db, kb, lock)
    return {"id": str(target), "deleted": delete}


async def health(db: Any, kb: RecordID, lock: WriteLock) -> dict[str, int]:
    pages = (
        await query(db, "SELECT * FROM repo_wiki_page WHERE kb=$kb;", {"kb": kb}) or []
    )
    files = await current_files(db, kb)
    current = {(f["repo"], f["path"]): f for f in files}
    sources = (
        await query(
            db, "SELECT * FROM repo_source WHERE kb=$kb AND enabled=true;", {"kb": kb}
        )
        or []
    )
    names = {s["name"]: s for s in sources}
    stored = (
        await query(
            db,
            "SELECT source,path,last_commit,lines FROM repo_file WHERE $sources CONTAINS source;",
            {"sources": [s["id"] for s in sources]},
        )
        or []
    )
    historical: dict[tuple[str, str], list[dict[str, Any]]] = {}
    by_id = {str(s["id"]): s["name"] for s in sources}
    for file in stored:
        historical.setdefault((by_id[str(file["source"])], file["path"]), []).append(
            file
        )
    linked = {"index"}
    invalid = stale = 0
    refs = {c["ref"]: c for p in pages for c in citations(p["body"])}
    for ref in refs.values():
        source = names.get(ref["repo"])
        key = (ref["repo"], ref["path"])
        candidates = historical.get(key, [])
        valid = [
            f
            for f in candidates
            if f.get("last_commit", "").startswith(ref["commit"])
            and 1 <= ref["start"] <= ref["end"] <= f["lines"]
        ]
        if not source or not valid or key not in current:
            invalid += 1
        elif not current[key].get("last_commit", "").startswith(ref["commit"]):
            stale += 1
    for p in pages:
        for href in re.findall(r"\]\(([^)#]+)", p["body"]):
            if "://" not in href:
                linked.add(
                    posixpath.normpath(
                        posixpath.join(
                            posixpath.dirname(p["slug"]), href.removesuffix(".md")
                        )
                    )
                )
    result = {
        "orphan_pages": sum(p["slug"] not in linked for p in pages),
        "invalid_citations": invalid,
        "stale_citations": stale,
        "stale_llm_pages": sum(
            p["stale"] and p["generated_by"] != "build" for p in pages
        ),
        "uncovered_modules": len(
            {f["module"] for f in files if f.get("module")}
            - {p["module"] for p in pages if p.get("module")}
        ),
    }
    await transaction(
        db, "UPDATE $kb SET health=$health;", {"kb": kb, "health": result}, lock
    )
    return result
