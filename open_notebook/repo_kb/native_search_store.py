"""Build isolated, compressed keyword-index generations in SurrealDB."""

from __future__ import annotations

import asyncio
import math
from collections import defaultdict
from typing import Any, Awaitable, Callable, Iterable
from uuid import uuid4

from surrealdb import RecordID

from open_notebook.repo_kb.native_search import (
    candidates,
    compile_postings,
    document_id,
    grams,
    posting_id,
)

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]
_BATCH_SIZE = 250


async def _run(query: Query, statement: str, params: dict[str, Any]) -> Any:
    result = await query(statement, params)
    if isinstance(result, str):
        raise RuntimeError("Search index database operation failed")
    return result


async def build_generation(
    query: Query, kb: RecordID, documents: Iterable[tuple[RecordID, str]]
) -> RecordID:
    """Build an unpublished snapshot from already masked, policy-checked text.

    The caller must hold the knowledge-base write lock. Publishing, cleanup,
    and invalidation on source or exclusion changes are separate operations.
    """
    if kb.table_name != "repo_kb":
        raise ValueError("Expected a repo_kb record")
    values = list(documents)
    if any(
        target.table_name not in {"repo_chunk", "repo_wiki_section"}
        for target, _ in values
    ):
        raise ValueError("Unsupported search target")
    count, postings = await asyncio.to_thread(
        compile_postings, (body for _, body in values)
    )
    generation = RecordID("repo_search_generation", uuid4().hex)
    kb_row = await _run(query, "SELECT * FROM ONLY $id;", {"id": kb})
    policy_version = kb_row.get("policy_version", 0) if isinstance(kb_row, dict) else 0
    await _run(
        query,
        "CREATE $id CONTENT $data;",
        {
            "id": generation,
            "data": {
                "kb": kb,
                "document_count": count,
                "policy_version": policy_version,
                "average_length": float(
                    sum(len(body) for _, body in values) / max(1, len(values))
                ),
            },
        },
    )
    doc_rows = [
        {
            "id": document_id(generation, ordinal),
            "generation": generation,
            "ordinal": ordinal,
            "target": target,
        }
        for ordinal, (target, _) in enumerate(values)
    ]
    posting_rows = [
        {
            "id": posting_id(generation, term),
            "generation": generation,
            "gram": term,
            "ids": data,
        }
        for term, data in postings.items()
    ]
    for table, rows in (
        ("repo_search_document", doc_rows),
        ("repo_search_posting", posting_rows),
    ):
        for start in range(0, len(rows), _BATCH_SIZE):
            await _run(
                query,
                f"INSERT INTO {table} $batch RETURN NONE;",
                {"batch": rows[start : start + _BATCH_SIZE]},
            )
    result = await _run(query, "UPDATE $id SET ready = true;", {"id": generation})
    if not isinstance(result, list) or len(result) != 1:
        raise RuntimeError("Search index generation could not be completed")
    return generation


async def publish_generation(query: Query, kb: RecordID, generation: RecordID) -> None:
    """Publish only a generation belonging to this knowledge base."""
    row = await _run(query, "SELECT * FROM ONLY $id;", {"id": generation})
    if not isinstance(row, dict) or row.get("kb") != kb or row.get("ready") is not True:
        raise ValueError("Search generation does not belong to this knowledge base")
    kb_row = await _run(query, "SELECT * FROM ONLY $id;", {"id": kb})
    if not isinstance(kb_row, dict) or row.get("policy_version", 0) != kb_row.get(
        "policy_version", 0
    ):
        raise ValueError("Knowledge base policy changed during index construction")
    result = await _run(
        query,
        "UPDATE $kb SET search_generation = $generation;",
        {"kb": kb, "generation": generation},
    )
    if not isinstance(result, list) or len(result) != 1:
        raise ValueError("Knowledge base not found")


async def invalidate_generation(query: Query, kb: RecordID) -> None:
    """Make stale postings unavailable before changing protected content."""
    await _run(query, "UPDATE $kb UNSET search_generation;", {"kb": kb})


async def candidate_targets(query: Query, kb: RecordID, text: str) -> list[RecordID]:
    """Find candidate targets; callers must enforce access and verify the text."""
    if not text:
        return []
    kb_row = await _run(query, "SELECT * FROM ONLY $id;", {"id": kb})
    if not isinstance(kb_row, dict) or not kb_row.get("search_generation"):
        return []
    generation = kb_row["search_generation"]
    gen_row = await _run(query, "SELECT * FROM ONLY $id;", {"id": generation})
    if (
        not isinstance(gen_row, dict)
        or gen_row.get("kb") != kb
        or gen_row.get("ready") is not True
        or gen_row.get("policy_version", 0) != kb_row.get("policy_version", 0)
    ):
        return []
    terms = grams(text)
    rows = (
        await _run(
            query,
            "SELECT gram, ids FROM $ids;",
            {"ids": [posting_id(generation, term) for term in sorted(terms)]},
        )
        if terms
        else []
    )
    if not isinstance(rows, list):
        raise RuntimeError("Search index lookup failed")
    postings = {row["gram"]: row["ids"] for row in rows}
    ordinals = candidates(text, postings, gen_row["document_count"])
    if not ordinals:
        return []
    documents = await _run(
        query,
        "SELECT generation, ordinal, target FROM $ids;",
        {"ids": [document_id(generation, ordinal) for ordinal in sorted(ordinals)]},
    )
    if not isinstance(documents, list):
        raise RuntimeError("Search document lookup failed")
    return [row["target"] for row in documents if row.get("generation") == generation]


async def ranked_targets(
    query: Query, generation: dict[str, Any], terms: list[str], limit: int = 1000
) -> tuple[list[RecordID], dict[str, int]]:
    """Fetch each posting once, rank ordinals, then resolve a bounded target set."""
    current = generation["id"]
    count = generation["document_count"]
    all_grams = {gram for term in terms for gram in grams(term)}
    rows = (
        await _run(
            query,
            "SELECT gram,ids FROM $ids;",
            {"ids": [posting_id(current, gram) for gram in sorted(all_grams)]},
        )
        if all_grams
        else []
    )
    postings = {row["gram"]: row["ids"] for row in rows}
    scores: dict[int, float] = defaultdict(float)
    frequencies = {}
    for term in terms:
        ordinals = candidates(term, postings, count)
        frequencies[term] = len(ordinals)
        weight = math.log(1 + (count - len(ordinals) + 0.5) / (len(ordinals) + 0.5))
        for ordinal in ordinals:
            scores[ordinal] += weight
    selected = sorted(scores, key=lambda ordinal: (-scores[ordinal], ordinal))[:limit]
    documents = (
        await _run(
            query,
            "SELECT target FROM $ids;",
            {"ids": [document_id(current, ordinal) for ordinal in selected]},
        )
        if selected
        else []
    )
    return [doc["target"] for doc in documents], frequencies
