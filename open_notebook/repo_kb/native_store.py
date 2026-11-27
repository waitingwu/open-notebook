"""Atomic native persistence of already masked source file content."""

from __future__ import annotations

import hashlib
from typing import Any, Awaitable, Callable
from uuid import uuid4

from surrealdb import RecordID

from open_notebook.repo_kb.native_ingest import PreparedFile
from open_notebook.repo_kb.native_lock import GUARD, WriteLock

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]


async def _checked(query: Query, sql: str, params: dict[str, Any]) -> list[Any]:
    result = await query(sql, params)
    statements = result.get("result") if isinstance(result, dict) else None
    if not isinstance(statements, list) or any(
        statement.get("status") != "OK" for statement in statements
    ):
        raise RuntimeError("Repo file transaction failed")
    return statements


async def create_snapshot(
    query: Query, source: RecordID, commit_sha: str, lock: WriteLock | None = None
) -> RecordID:
    if source.table_name != "repo_source" or not commit_sha:
        raise ValueError("A source and commit are required")
    snapshot = RecordID("repo_source_snapshot", uuid4().hex)
    guard = (
        (
            GUARD
            + " LET $src = SELECT * FROM ONLY $source; IF $src = NONE OR $src.kb != $lock_kb { THROW 'Lock scope mismatch'; };"
        )
        if lock
        else ""
    )
    params = {"id": snapshot, "data": {"source": source, "commit_sha": commit_sha}}
    if lock:
        params.update(lock.params())
        params["source"] = source
    await _checked(
        query,
        f"BEGIN TRANSACTION; {guard} CREATE $id CONTENT $data; COMMIT TRANSACTION;",
        params,
    )
    return snapshot


async def activate_snapshot(
    query: Query,
    source: RecordID,
    snapshot: RecordID,
    kb: RecordID,
    commit_sha: str,
    file_count: int,
    lock: WriteLock | None = None,
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
    if lock and lock.kb != kb:
        raise ValueError("Lock does not belong to this knowledge base")
    # Conditions ensure a stale/mismatched staging operation cannot overwrite
    # another source. A failed condition aborts the entire transaction.
    sql = """
        BEGIN TRANSACTION;
        __GUARD__
        LET $s = SELECT * FROM ONLY $source;
        LET $knowledge_base = SELECT * FROM ONLY $kb;
        LET $snapshot_row = SELECT * FROM ONLY $snapshot;
        LET $files = SELECT count() AS total FROM repo_file WHERE snapshot = $snapshot GROUP ALL;
        IF $knowledge_base = NONE OR $s = NONE OR $s.kb != $kb OR $snapshot_row = NONE OR $snapshot_row.source != $source OR $snapshot_row.commit_sha != $commit OR $snapshot_row.ready = true OR ($files[0].total ?? 0) != $file_count {
            THROW 'Invalid snapshot activation';
        };
        UPDATE $snapshot SET ready = true, file_count = $file_count;
        UPDATE $source SET current_snapshot = $snapshot, last_commit = $commit,
            file_count = $file_count, last_synced_at = time::now(), status = 'ok';
        UPDATE $kb SET stale = true;
        UPDATE $kb UNSET search_generation;
        COMMIT TRANSACTION;
    """
    params = {
        "source": source,
        "snapshot": snapshot,
        "kb": kb,
        "commit": commit_sha,
        "file_count": file_count,
    }
    if lock:
        params.update(lock.params())
    await _checked(query, sql.replace("__GUARD__", GUARD if lock else ""), params)


def file_id(source: RecordID, snapshot: RecordID, path: str) -> RecordID:
    """Stable identifiers make retries idempotent without exposing paths as IDs."""
    key = hashlib.sha256(
        (str(source) + "\0" + str(snapshot) + "\0" + path).encode()
    ).hexdigest()
    return RecordID("repo_file", key)


async def replace_file(
    query: Query,
    source: RecordID,
    snapshot: RecordID,
    prepared: PreparedFile,
    lock: WriteLock | None = None,
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
        GUARD if lock else "",
        "LET $stage = SELECT * FROM ONLY $snapshot;",
        "IF $stage = NONE OR $stage.source != $source OR $stage.ready = true { THROW 'Invalid snapshot'; };",
        "DELETE repo_chunk WHERE file = $target;",
        "UPSERT $target CONTENT $metadata;",
        "UPDATE $target SET last_commit = $stage.commit_sha;",
    ]
    if chunks:
        statements.append("INSERT INTO repo_chunk $chunks RETURN NONE;")
    statements.append("COMMIT TRANSACTION;")
    params = {
        "target": target,
        "metadata": metadata,
        "chunks": chunks,
        "source": source,
        "snapshot": snapshot,
    }
    if lock:
        params.update(lock.params())
        statements.insert(
            3,
            "LET $src = SELECT * FROM ONLY $source; IF $src = NONE OR $src.kb != $lock_kb { THROW 'Lock scope mismatch'; };",
        )
    await _checked(query, "\n".join(statements), params)
