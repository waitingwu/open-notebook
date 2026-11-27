"""Atomic native persistence of already masked source file content."""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable

from surrealdb import RecordID

from open_notebook.repo_kb.native_ingest import PreparedFile

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]


def file_id(source: RecordID, path: str) -> RecordID:
    """Stable identifiers make retries idempotent without exposing paths as IDs."""
    key = hashlib.sha256((str(source) + "\0" + path).encode()).hexdigest()
    return RecordID("repo_file", key)


async def replace_file(query: Query, source: RecordID, prepared: PreparedFile) -> None:
    """Replace one file and its chunks in a single transaction.

    A whole-source sync still requires staging and an atomic activation step;
    this operation does not provide that higher-level guarantee.
    """
    if source.table_name != "repo_source":
        raise ValueError("Expected a repo_source record")
    target = file_id(source, prepared.path)
    metadata = {
        "source": source,
        "path": prepared.path,
        "blob": prepared.blob,
        "category": prepared.category,
        "module": prepared.module,
        "method": prepared.method,
        "lines": prepared.lines,
        "masks": prepared.masks,
        "converted": bool(prepared.chunks) and prepared.method != "text",
    }
    chunks = [
        {
            "file": target,
            "source": source,
            "path": prepared.path,
            "category": prepared.category,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "body": chunk.body,
        }
        for chunk in prepared.chunks
    ]
    statements = [
        "BEGIN TRANSACTION;",
        "DELETE repo_chunk WHERE file = $target;",
        "UPSERT $target CONTENT $metadata;",
    ]
    if chunks:
        statements.append("INSERT INTO repo_chunk $chunks RETURN NONE;")
    statements.append("COMMIT TRANSACTION;")
    result = await query(
        "\n".join(statements),
        {"target": target, "metadata": metadata, "chunks": chunks},
    )
    statements_result = result.get("result") if isinstance(result, dict) else None
    if not isinstance(statements_result, list) or any(
        statement.get("status") != "OK" for statement in statements_result
    ):
        # Database errors can include source values; do not put them in logs.
        raise RuntimeError("Repo file transaction failed")
