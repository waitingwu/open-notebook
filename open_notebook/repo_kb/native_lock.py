"""Leased knowledge-base write lock with transaction-level fencing."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from surrealdb import RecordID

from open_notebook.exceptions import ConflictError

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]


class KnowledgeBaseBusy(ConflictError):
    def __init__(self, job_id: str | None = None):
        super().__init__(
            "A knowledge base write operation is already queued or running"
        )
        self.job_id = job_id


@dataclass(frozen=True)
class WriteLock:
    id: RecordID
    kb: RecordID
    token: str

    def params(self) -> dict[str, Any]:
        return {"lock": self.id, "lock_kb": self.kb, "lock_token": self.token}


# Must be executed inside the same transaction as the guarded writes.  A
# transaction conflict invalidates the whole write if another job takes over.
GUARD = """
    LET $lease = SELECT * FROM ONLY $lock;
    IF $lease = NONE OR $lease.kb != $lock_kb OR $lease.token != $lock_token OR $lease.expires <= time::now() {
        THROW 'Knowledge base write lease is unavailable';
    };
    UPDATE $lock SET expires = time::now() + 5m;
"""


async def _execute(query: Query, sql: str, params: dict[str, Any]) -> None:
    result = await query(sql, params)
    statements = result.get("result") if isinstance(result, dict) else None
    if not isinstance(statements, list) or any(
        row.get("status") != "OK" for row in statements
    ):
        raise RuntimeError("Knowledge base write lock unavailable")


async def acquire(query: Query, kb: RecordID) -> WriteLock:
    if kb.table_name != "repo_kb":
        raise ValueError("Expected a repo_kb record")
    lock = WriteLock(
        RecordID("repo_kb_lock", hashlib.sha256(str(kb).encode()).hexdigest()),
        kb,
        secrets.token_hex(16),
    )
    sql = """
        BEGIN TRANSACTION;
        LET $existing = SELECT * FROM ONLY $lock;
        IF $existing != NONE AND $existing.expires > time::now() { THROW 'Knowledge base busy'; };
        UPSERT $lock SET kb = $lock_kb, token = $lock_token, expires = time::now() + 5m;
        COMMIT TRANSACTION;
    """
    try:
        await _execute(query, sql, lock.params())
    except RuntimeError as exc:
        response = await query("SELECT job_id FROM ONLY $id;", {"id": lock.id})
        entries = response.get("result", [])
        row = entries[-1].get("result") if entries else None
        if isinstance(row, dict):
            raise KnowledgeBaseBusy(row.get("job_id")) from exc
        raise
    return lock


async def release(query: Query, lock: WriteLock) -> None:
    await _execute(query, "DELETE $lock WHERE token = $lock_token;", lock.params())
