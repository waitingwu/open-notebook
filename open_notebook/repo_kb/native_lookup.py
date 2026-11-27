"""Current-policy keyword retrieval with application-side BM25 ranking."""

from __future__ import annotations

import math
import re
from collections import defaultdict
from typing import Any

from surrealdb import RecordID

from open_notebook.repo_kb.native_access import check_policy_version, current_files
from open_notebook.repo_kb.native_db import query, visible_kb
from open_notebook.repo_kb.native_pages import page_readable
from open_notebook.repo_kb.native_search import grams
from open_notebook.repo_kb.native_search_store import candidate_targets


def query_terms(text: str) -> list[str]:
    terms = re.findall(
        r"[a-zA-Z0-9_]+(?:[=-]-?[a-zA-Z0-9_]+)?|[\u3400-\u9fff]+", text.casefold()
    )
    return list(
        dict.fromkeys(
            term
            for value in terms
            for term in (
                sorted(grams(value))
                if len(value) > 6 and re.fullmatch(r"[\u3400-\u9fff]+", value)
                else [value]
            )
        )
    )[:64]


async def search(
    db: Any,
    kb_id: RecordID,
    text: str,
    *,
    category: str | None = None,
    module: str | None = None,
    limit: int = 10,
    target_kind: str | None = None,
) -> list[dict[str, Any]]:
    kb = await visible_kb(db, kb_id)
    if not text.strip() or not kb.get("search_generation"):
        return []
    generation = await query(
        db, "SELECT * FROM ONLY $id;", {"id": kb["search_generation"]}
    )
    if not isinstance(generation, dict):
        return []
    count = max(1, generation["document_count"])
    terms = query_terms(text)
    matches: dict[str, set[str]] = {}
    scores: dict[str, float] = defaultdict(float)
    for term in terms:
        matches[term] = set(
            str(value)
            for value in await candidate_targets(
                lambda sql, params: query(db, sql, params), kb_id, term
            )
        )
        idf = math.log(
            1 + (count - len(matches[term]) + 0.5) / (len(matches[term]) + 0.5)
        )
        for target in matches[term]:
            scores[target] += idf
    # Rank using posting-level IDF before fetching bodies; this bounds memory
    # for common Chinese bigrams without reading an entire repository per turn.
    targets = sorted(scores, key=lambda key: (-scores[key], str(key)))[:1000]
    files = {str(row["id"]): row for row in await current_files(db, kb_id)}
    pages = (
        await query(
            db,
            "SELECT id,kb,slug,title,kind,module,dependencies FROM repo_wiki_page WHERE kb=$kb;",
            {"kb": kb_id},
        )
        or []
    )
    readable_pages = {
        str(row["id"]): row for row in pages if await page_readable(db, kb_id, row)
    }
    metadata = (
        await query(
            db,
            "SELECT id,file,page,category FROM $ids;",
            {"ids": [RecordID.parse(value) for value in targets]},
        )
        if targets
        else []
    )
    allowed = []
    for row in metadata or []:
        file = files.get(str(row.get("file")))
        page = readable_pages.get(str(row.get("page")))
        if target_kind == "source" and not file or target_kind == "wiki" and not page:
            continue
        if (
            file
            and (not category or file["category"] == category)
            and (not module or file.get("module") == module)
        ):
            allowed.append(row["id"])
        elif page and not category and (not module or page.get("module") == module):
            allowed.append(row["id"])
    rows = await query(db, "SELECT * FROM $ids;", {"ids": allowed}) if allowed else []
    results = []
    average = max(1.0, generation.get("average_length", 1.0))
    for row in rows or []:
        body = row["body"]
        normalized = body.casefold()
        score = 0.0
        positions = []
        for term in terms:
            tf = normalized.count(term)
            if not tf:
                continue
            positions.append(normalized.find(term))
            df = len(matches[term])
            score += (
                math.log(1 + (count - df + 0.5) / (df + 0.5))
                * tf
                * 2.2
                / (tf + 1.2 * (0.25 + 0.75 * len(body) / average))
            )
        if not score:
            continue
        offset = max(0, min(positions) - 100)
        result: dict[str, Any] = {
            "id": str(row["id"]),
            "body": body[offset : offset + 1200],
            "score": score,
        }
        file = files.get(str(row.get("file")))
        if file:
            result.update(
                {
                    "path": file["path"],
                    "repo": file["repo"],
                    "category": file["category"],
                    "module": file.get("module"),
                    "ref": f"〔{file['repo']}:{file['path']}#L{row['start_line']}-L{row['end_line']}@{file['last_commit'][:10]}〕",
                }
            )
        else:
            page = readable_pages[str(row["page"])]
            result.update(
                {
                    "slug": page["slug"],
                    "title": page["title"],
                    "kind": page["kind"],
                    "heading": row["heading"],
                }
            )
        results.append(result)
    await check_policy_version(db, kb_id, kb.get("policy_version", 0))
    return sorted(results, key=lambda row: -row["score"])[: max(1, min(limit, 50))]
