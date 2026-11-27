"""Atomic native persistence of already masked source file content."""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable
from uuid import uuid4

from surrealdb import RecordID

from open_notebook.repo_kb.native_ingest import PreparedFile

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]


async def _checked(query: Query, sql: str, params: dict[str, Any]) -> list[Any]:
    result = await query(sql, params)
    statements = result.get("result") if isinstance(result, dict) else None
    if not isinstance(statements, list) or any(
        statement.get("status") != "OK" for statement in statements
    ):
        raise RuntimeError("Repo file transaction failed")
    return statements


async def create_snapshot(query: Query, source: RecordID, commit_sha: str) -> RecordID:
    if source.table_name != "repo_source" or not commit_sha:
        raise ValueError("A source and commit are required")
    snapshot = RecordID("repo_source_snapshot", uuid4().hex)
    await _checked(
        query,
        "CREATE $id CONTENT $data;",
        {"id": snapshot, "data": {"source": source, "commit_sha": commit_sha}},
    )
    return snapshot


async def activate_snapshot(
    query: Query,
    source: RecordID,
    snapshot: RecordID,
    kb: RecordID,
    commit_sha: str,
    file_count: int,
) -> None:
    """Activate a complete snapshot and invalidate search in one transaction.

    The caller must hold the KB write lock and verify snapshot completeness.
    """
    if (
        source.table_name != "repo_source"
        or snapshot.table_name != "repo_source_snapshot"
        or kb.table_name != "repo_kb"
    ):
        raise ValueError("Invalid snapshot activation records")
    if file_count < 0 or not commit_sha:
        raise ValueError("Invalid snapshot metadata")
    # Conditions ensure a stale/mismatched staging operation cannot overwrite
    # another source. A failed condition aborts the entire transaction.
    sql = """
        BEGIN TRANSACTION;
        LET $s = SELECT * FROM ONLY $source;
        LET $snapshot_row = SELECT * FROM ONLY $snapshot;
        LET $files = SELECT count() AS total FROM repo_file WHERE snapshot = $snapshot GROUP ALL;
        IF $s = NONE OR $s.kb != $kb OR $snapshot_row = NONE OR $snapshot_row.source != $source OR $snapshot_row.commit_sha != $commit OR $snapshot_row.ready = true OR ($files[0].total ?? 0) != $file_count {
            THROW 'Invalid snapshot activation';
        };
        UPDATE $snapshot SET ready = true, file_count = $file_count;
        UPDATE $source SET current_snapshot = $snapshot, last_commit = $commit,
            file_count = $file_count, last_synced_at = time::now(), status = 'ok';
        UPDATE $kb UNSET search_generation;
        COMMIT TRANSACTION;
    """
    await _checked(
        query,
        sql,
        {
            "source": source,
            "snapshot": snapshot,
            "kb": kb,
            "commit": commit_sha,
            "file_count": file_count,
        },
    )


def file_id(source: RecordID, snapshot: RecordID, path: str) -> RecordID:
    """Stable identifiers make retries idempotent without exposing paths as IDs."""
    key = hashlib.sha256(
        (str(source) + "\0" + str(snapshot) + "\0" + path).encode()
    ).hexdigest()
    return RecordID("repo_file", key)


async def replace_file(
    query: Query, source: RecordID, snapshot: RecordID, prepared: PreparedFile
) -> None:
    """Replace one file and its chunks in a single transaction.

    A whole-source sync still requires staging and an atomic activation step;
    this operation does not provide that higher-level guarantee.
    """
    if source.table_name != "repo_source":
        raise ValueError("Expected a repo_source record")
    if snapshot.table_name != "repo_source_snapshot":
        raise ValueError("Expected a repo_source_snapshot record")
    target = file_id(source, snapshot, prepared.path)
    metadata = {
        "source": source,
        "snapshot": snapshot,
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
            "snapshot": snapshot,
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
        "LET $stage = SELECT * FROM ONLY $snapshot;",
        "IF $stage = NONE OR $stage.source != $source OR $stage.ready = true { THROW 'Invalid snapshot'; };",
        "DELETE repo_chunk WHERE file = $target;",
        "UPSERT $target CONTENT $metadata;",
        "UPDATE $target SET last_commit = $stage.commit_sha;",
    ]
    if chunks:
        statements.append("INSERT INTO repo_chunk $chunks RETURN NONE;")
    statements.append("COMMIT TRANSACTION;")
    await _checked(
        query,
        "\n".join(statements),
        {
            "target": target,
            "metadata": metadata,
            "chunks": chunks,
            "source": source,
            "snapshot": snapshot,
        },
    )
