"""Publish wiki pages into a CaBook (Open Notebook) notebook as text sources.

Goes through the public REST API, so the usual processing pipeline, auth and
audit apply. Idempotent: a page is re-published only when its content changed
(tracked in the ``published`` table), and pages removed from the wiki are
deleted from the notebook.
"""

from __future__ import annotations

import glob
import hashlib
import os
import re
from typing import Any, Dict, List, Optional

import httpx

from open_notebook.repo_kb.store import Store

DEFAULT_PAGES = [
    "index.md",
    "systems/*.md",
    "modules/*.md",
    "rules/*.md",
    "sop/index.md",
    "discrepancies.md",
    "tables/index.md",
]


def _strip_frontmatter(text: str) -> str:
    return re.sub(r"(?s)\A---\n.*?\n---\n", "", text)


def publish(
    store: Store,
    api: str,
    notebook_name: str,
    patterns: Optional[List[str]] = None,
    tables: Optional[List[str]] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    root = store.abs("wiki")
    pages: List[str] = []
    for pat in patterns or DEFAULT_PAGES:
        pages += sorted(
            os.path.relpath(p, root) for p in glob.glob(os.path.join(root, pat))
        )
    for t in tables or []:
        if os.path.exists(os.path.join(root, f"tables/{t}.md")):
            pages.append(f"tables/{t}.md")
    headers = {"Authorization": f"Bearer {password}"} if password else {}
    store.db.execute(
        "CREATE TABLE IF NOT EXISTS published (page TEXT PRIMARY KEY, notebook TEXT, source_id TEXT, sha TEXT)"
    )
    with httpx.Client(base_url=api, headers=headers, timeout=120) as http:
        nbs = http.get("/api/notebooks").raise_for_status().json()
        nb = next((n for n in nbs if n["name"] == notebook_name), None)
        if nb is None:
            nb = (
                http.post(
                    "/api/notebooks",
                    json={
                        "name": notebook_name,
                        "description": "由 Repo KB 從 git repo 自動產生的分層維運知識庫（系統／模組、資料表、業務規則、SOP、spec 與程式不一致清單）。",
                    },
                )
                .raise_for_status()
                .json()
            )
        created: List[str] = []
        updated: List[str] = []
        unchanged: List[str] = []
        removed: List[str] = []
        for page in pages:
            with open(os.path.join(root, page), encoding="utf-8") as f:
                content = _strip_frontmatter(f.read())
            sha = hashlib.sha1(content.encode()).hexdigest()
            prev = store.db.execute(
                "SELECT source_id, sha FROM published WHERE page=? AND notebook=?",
                (page, nb["id"]),
            ).fetchone()
            if prev and prev["sha"] == sha:
                unchanged.append(page)
                continue
            if prev:
                http.delete(f"/api/sources/{prev['source_id']}")
            first = next(
                (ln for ln in content.split("\n") if ln.startswith("# ")), page
            )
            title = f"[AV KB] {page[:-3]}｜{first[2:].strip()}"[:180]
            src = (
                http.post(
                    "/api/sources/json",
                    json={
                        "type": "text",
                        "content": content,
                        "title": title,
                        "notebooks": [nb["id"]],
                        "embed": False,
                    },
                )
                .raise_for_status()
                .json()
            )
            store.db.execute(
                "INSERT OR REPLACE INTO published VALUES (?,?,?,?)",
                (page, nb["id"], src["id"], sha),
            )
            (updated if prev else created).append(page)
        for row in list(
            store.db.execute(
                "SELECT page, source_id FROM published WHERE notebook=?", (nb["id"],)
            )
        ):
            if row["page"] not in pages:
                http.delete(f"/api/sources/{row['source_id']}")
                store.db.execute(
                    "DELETE FROM published WHERE page=? AND notebook=?",
                    (row["page"], nb["id"]),
                )
                removed.append(row["page"])
    store.event(
        "publish",
        "*",
        {
            "notebook": nb["id"],
            "created": len(created),
            "updated": len(updated),
            "removed": len(removed),
        },
    )
    store.db.commit()
    return {
        "notebook_id": nb["id"],
        "created": len(created),
        "updated": updated,
        "unchanged": len(unchanged),
        "removed": removed,
    }
