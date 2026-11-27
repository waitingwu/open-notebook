"""Current-policy reads; never fetch protected chunk bodies or inactive snapshots."""

from __future__ import annotations

from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import NotFoundError
from open_notebook.repo_kb.native_db import one, query, visible_kb
from open_notebook.repo_kb.protected_rules import NativePathRules, ProtectedRule


def source_rules(source: dict[str, Any]) -> NativePathRules:
    return NativePathRules(
        source.get("include", []),
        source.get("exclude", []),
        [ProtectedRule(**r) for r in source.get("protected", [])],
    )


async def current_files(db: Any, kb: RecordID) -> list[dict[str, Any]]:
    sources = await query(
        db, "SELECT * FROM repo_source WHERE kb=$kb AND enabled=true;", {"kb": kb}
    )
    files: list[dict[str, Any]] = []
    for source in sources or []:
        if not source.get("current_snapshot"):
            continue
        rows = await query(
            db,
            "SELECT * FROM repo_file WHERE source=$source AND snapshot=$snapshot;",
            {"source": source["id"], "snapshot": source["current_snapshot"]},
        )
        rules = source_rules(source)
        files.extend(
            {**row, "repo": source["name"], "source_row": source}
            for row in rows or []
            if rules.allows_file(row["path"])
        )
    return files


async def readable_file(db: Any, kb: RecordID, file: RecordID) -> dict[str, Any]:
    row = await one(db, file, "repo_file")
    source = await one(db, row["source"], "repo_source")
    if (
        source["kb"] != kb
        or not source["enabled"]
        or source.get("current_snapshot") != row["snapshot"]
        or not source_rules(source).allows_file(row["path"])
    ):
        raise NotFoundError("Source content is not available")
    return {**row, "repo": source["name"], "source_row": source}


async def file_chunks(db: Any, kb: RecordID, file: RecordID) -> list[dict[str, Any]]:
    await readable_file(db, kb, file)
    return (
        await query(
            db,
            "SELECT * FROM repo_chunk WHERE file=$file ORDER BY start_line;",
            {"file": file},
        )
        or []
    )


def reconstruct_text(file: dict[str, Any], chunks: list[dict[str, Any]]) -> str:
    lines = [""] * file["lines"]
    for chunk in chunks:
        start = chunk["start_line"] - 1
        values = chunk["body"].split("\n")
        lines[start : start + len(values)] = values
    return "\n".join(lines)


async def check_policy_version(db: Any, kb: RecordID, version: int) -> None:
    current = await visible_kb(db, kb)
    if current.get("policy_version", 0) != version:
        raise NotFoundError("Knowledge base policy changed; retry the request")
