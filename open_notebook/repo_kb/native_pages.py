"""Versioned wiki pages, searchable sections, and preserved manual notes."""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.repo_kb.mask import mask_text
from open_notebook.repo_kb.native_cite import citations, validate
from open_notebook.repo_kb.native_db import one, query, transaction
from open_notebook.repo_kb.native_lock import WriteLock
from open_notebook.repo_kb.native_render import Page


def page_id(kb: RecordID, slug: str) -> RecordID:
    if (
        not slug
        or slug.startswith("/")
        or any(part in {"", ".", ".."} for part in slug.split("/"))
    ):
        raise InvalidInputError("Invalid wiki page slug")
    return RecordID(
        "repo_wiki_page", hashlib.sha256((str(kb) + "\0" + slug).encode()).hexdigest()
    )


def sections(page: RecordID, kb: RecordID, body: str) -> list[dict[str, Any]]:
    parts = re.split(r"(?m)^(?=#{2,3} )", body)
    return [
        {
            "page": page,
            "kb": kb,
            "heading": (
                part.splitlines()[0].lstrip("# ")[:240] if part.splitlines() else ""
            ),
            "body": part,
            "citations": citations(part),
        }
        for part in parts
        if part.strip()
    ]


async def get_page(db: Any, kb: RecordID, slug: str) -> dict[str, Any]:
    page = await one(db, page_id(kb, slug), "repo_wiki_page")
    if page["kb"] != kb:
        raise NotFoundError("Wiki page not found")
    return page


async def save_page(
    db: Any,
    kb: RecordID,
    value: Page,
    lock: WriteLock,
    *,
    generated_by: str = "build",
    model: str | None = None,
    dependencies: list[dict[str, Any]] | None = None,
    source_commits: dict[str, str] | None = None,
    check_citations: bool = True,
) -> dict[str, Any]:
    if lock.kb != kb:
        raise InvalidInputError("Wiki write lock scope mismatch")
    body = mask_text(value.body)[0]
    if check_citations:
        report = await validate(db, kb, body)
        if report["invalid"]:
            raise InvalidInputError(
                "Wiki page contains citations that cannot be verified"
            )
    target = page_id(kb, value.slug)
    previous = await query(db, "SELECT * FROM ONLY $id;", {"id": target})
    version = (previous.get("revision", 0) if isinstance(previous, dict) else 0) + 1
    notes = (
        await query(
            db, "SELECT * FROM repo_wiki_note WHERE page=$page;", {"page": target}
        )
        or []
    )
    note_text = "\n\n".join(note["body"] for note in notes)
    data = {
        "kb": kb,
        "slug": value.slug,
        "kind": value.kind,
        "title": mask_text(value.title)[0],
        "summary": mask_text(value.summary)[0],
        "module": value.module,
        "body": body,
        "content_hash": hashlib.sha256(body.encode()).hexdigest(),
        "citations": citations(body),
        "generated_by": generated_by,
        "model": model,
        "source_commits": source_commits or {},
        "dependencies": dependencies or [],
        "revision": version,
        "stale": False,
        "updated": datetime.now(timezone.utc),
    }
    revision = {
        "page": target,
        "revision": version,
        "body": body,
        "summary": data["summary"],
        "citations": data["citations"],
        "generated_by": generated_by,
        "model": model,
        "source_commits": source_commits or {},
        "dependencies": dependencies or [],
    }
    sql = "UPSERT $id CONTENT $data; UPDATE $id SET updated=time::now(); CREATE repo_wiki_revision CONTENT $revision; DELETE repo_wiki_section WHERE page=$id;"
    segments = sections(
        target, kb, body + ("\n\n## 人工補充\n" + note_text if note_text else "")
    )
    if segments:
        sql += " INSERT INTO repo_wiki_section $sections RETURN NONE;"
    if (
        isinstance(previous, dict)
        and previous.get("content_hash") != data["content_hash"]
    ):
        sql += " UPDATE repo_wiki_note SET stale=true WHERE page=$id;"
    await transaction(
        db,
        sql,
        {"id": target, "data": data, "revision": revision, "sections": segments},
        lock,
    )
    return {"id": str(target), "slug": value.slug, "revision": version}


async def page_readable(
    db: Any,
    kb: RecordID,
    page: dict[str, Any],
    sources: dict[str, dict[str, Any]] | None = None,
) -> bool:
    # Protection invalidates pages transactionally. Dependencies additionally
    # prevent old revisions from bypassing current source policy.
    from open_notebook.repo_kb.native_access import source_rules

    for dep in page.get("dependencies", []):
        source = (
            sources.get(str(dep["source"]))
            if sources is not None
            else await query(
                db,
                "SELECT * FROM ONLY $id;",
                {"id": RecordID.parse(str(dep["source"]))},
            )
        )
        if (
            not isinstance(source, dict)
            or source["kb"] != kb
            or not source["enabled"]
            or (dep.get("path") and not source_rules(source).allows_file(dep["path"]))
        ):
            return False
    return True
