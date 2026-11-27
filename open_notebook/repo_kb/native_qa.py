"""Save a persisted assistant response as a citation-validated wiki page."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.repo_kb.native_cite import citations, validate
from open_notebook.repo_kb.native_db import one, query, record, visible_kb
from open_notebook.repo_kb.native_lock import acquire, release
from open_notebook.repo_kb.native_pages import save_page
from open_notebook.repo_kb.native_render import Page


async def save_answer(
    db: Any, kb: RecordID, session_id: str, message_id: str, title: str
) -> dict[str, Any]:
    from open_notebook.graphs.chat import graph
    from open_notebook.repo_kb.native_wiki import build_wiki

    session = record(session_id, "chat_session")
    await one(db, session, "chat_session")
    relations = (
        await query(db, "SELECT out FROM refers_to WHERE in=$id;", {"id": session})
        or []
    )
    notebooks = [
        r["out"] for r in relations if getattr(r["out"], "table_name", "") == "notebook"
    ]
    if not notebooks:
        raise NotFoundError("Notebook chat not found")
    await visible_kb(db, kb, notebooks[0])
    state = await asyncio.to_thread(
        graph.get_state, {"configurable": {"thread_id": str(session)}}
    )
    messages = state.values.get("messages", []) if state else []
    message = next((m for m in messages if m.id == message_id and m.type == "ai"), None)
    if message is None or not isinstance(message.content, str):
        raise NotFoundError("Assistant answer not found")
    lock = await acquire(db.query_raw, kb)
    try:
        report = await validate(db, kb, message.content)
        if not report["total"] or report["invalid"]:
            raise InvalidInputError(
                "Only answers with verifiable citations can be saved"
            )
        sources = (
            await query(
                db,
                "SELECT * FROM repo_source WHERE kb=$kb AND enabled=true;",
                {"kb": kb},
            )
            or []
        )
        by_name = {s["name"]: s for s in sources}
        dependencies = [
            {"source": str(by_name[c["repo"]]["id"]), "path": c["path"]}
            for c in citations(message.content)
        ]
        slug = (
            "qa/"
            + hashlib.sha256((str(session) + message_id).encode()).hexdigest()[:20]
        )
        result = await save_page(
            db,
            kb,
            Page(
                slug, "qa", title, title[:240], "# " + title + "\n\n" + message.content
            ),
            lock,
            generated_by="qa-save",
            dependencies=dependencies,
            source_commits={
                s["name"]: s["last_commit"] for s in sources if s.get("last_commit")
            },
        )
        await build_wiki(db, kb, lock)
        return result
    finally:
        await release(db.query_raw, lock)
