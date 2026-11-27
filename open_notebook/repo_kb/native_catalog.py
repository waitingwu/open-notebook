"""Validated creation of native knowledge bases and their git sources."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any, Awaitable, Callable, Optional

from surrealdb import RecordID

from open_notebook.repo_kb.native_paths import validate_source_path
from open_notebook.repo_kb.protected_rules import ProtectedRule

Query = Callable[[str, dict[str, Any]], Awaitable[Any]]
_SOURCE_NAME = re.compile(r"^[a-z0-9_-]{1,32}$")


async def create_kb(
    query: Query,
    *,
    name: str,
    description: Optional[str] = None,
    owner_notebook: Optional[RecordID] = None,
) -> dict[str, Any]:
    name = name.strip()
    if not name:
        raise ValueError("Knowledge base name is required")
    if owner_notebook is not None:
        if owner_notebook.table_name != "notebook":
            raise ValueError("Expected a notebook record")
        existing = await query("SELECT id FROM ONLY $id;", {"id": owner_notebook})
        if not existing:
            raise ValueError("Notebook not found")
    result = await query(
        "CREATE repo_kb CONTENT $data;",
        {
            "data": {
                "name": name,
                "description": description,
                "scope": "notebook" if owner_notebook else "global",
                "owner_notebook": owner_notebook,
            }
        },
    )
    if not isinstance(result, list) or len(result) != 1:
        raise RuntimeError("Failed to create knowledge base")
    return result[0]


async def create_source(
    query: Query,
    *,
    kb: RecordID,
    name: str,
    path: str,
    role: str,
    include: list[str],
    exclude: list[str],
    protected: list[ProtectedRule],
    allowed_roots: list[str],
    data_roots: list[str],
) -> dict[str, Any]:
    if kb.table_name != "repo_kb" or not await query(
        "SELECT id FROM ONLY $id;", {"id": kb}
    ):
        raise ValueError("Knowledge base not found")
    if not _SOURCE_NAME.fullmatch(name):
        raise ValueError("Invalid source name")
    if role not in {"doc", "src"}:
        raise ValueError("Invalid source role")
    root = validate_source_path(
        path, allowed_roots=allowed_roots, data_roots=data_roots
    )
    result = await query(
        "CREATE repo_source CONTENT $data;",
        {
            "data": {
                "kb": kb,
                "name": name,
                "path": str(root),
                "role": role,
                "include": include,
                "exclude": exclude,
                "protected": [asdict(rule) for rule in protected],
            }
        },
    )
    if not isinstance(result, list) or len(result) != 1:
        raise RuntimeError("Failed to create source")
    return result[0]
