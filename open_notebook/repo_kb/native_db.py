"""Shared, sanitised database operations for the native repo knowledge base."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import InvalidInputError, NotFoundError
from open_notebook.repo_kb.native_lock import GUARD, WriteLock


def record(value: str | RecordID, table: str) -> RecordID:
    try:
        result = (
            value
            if isinstance(value, RecordID)
            else RecordID.parse(value if ":" in value else f"{table}:{value}")
        )
        if result.table_name != table:
            raise ValueError()
        return result
    except (ValueError, TypeError, AttributeError) as exc:
        raise InvalidInputError(f"Invalid {table} identifier") from exc


async def query(db: Any, sql: str, params: dict[str, Any] | None = None) -> Any:
    response = await db.query_raw(sql, params or {})
    results = response.get("result") if isinstance(response, dict) else None
    if not isinstance(results, list) or any(
        row.get("status") != "OK" for row in results
    ):
        raise RuntimeError("Knowledge base database operation failed")
    return results[-1].get("result") if results else None


async def one(db: Any, value: str | RecordID, table: str) -> dict[str, Any]:
    row = await query(db, "SELECT * FROM ONLY $id;", {"id": record(value, table)})
    if not isinstance(row, dict):
        raise NotFoundError(f"{table} not found")
    return row


async def transaction(
    db: Any, sql: str, params: dict[str, Any], lock: WriteLock
) -> Any:
    return await query(
        db,
        "BEGIN TRANSACTION;\n" + GUARD + "\n" + sql + "\nCOMMIT TRANSACTION;",
        {**params, **lock.params()},
    )


async def visible_kb(
    db: Any, kb: str | RecordID, notebook: str | RecordID | None = None
) -> dict[str, Any]:
    row = await one(db, kb, "repo_kb")
    if (
        notebook is not None
        and row["scope"] == "notebook"
        and row.get("owner_notebook") != record(notebook, "notebook")
    ):
        raise NotFoundError("Knowledge base not available in this notebook")
    return row


def config_hash(source: dict[str, Any]) -> str:
    data = {
        key: source.get(key)
        for key in ("path", "role", "include", "exclude", "protected", "enabled")
    }
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def public_job(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value for key, value in row.items() if key not in {"lock_token", "options"}
    }
