"""Stage a read-only git source into an atomic native database snapshot."""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from typing import Any, Awaitable, Callable, Protocol

from surrealdb import RecordID

from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.native_ingest import (
    PreparedChunk,
    PreparedFile,
    prepare_entry,
)
from open_notebook.repo_kb.native_lock import WriteLock, acquire, release
from open_notebook.repo_kb.native_paths import validate_source_path
from open_notebook.repo_kb.native_store import (
    activate_snapshot,
    create_snapshot,
    replace_file,
)
from open_notebook.repo_kb.protected_rules import NativePathRules, ProtectedRule


class Database(Protocol):
    async def query(self, query: str, vars: dict[str, Any]) -> Any: ...
    async def query_raw(self, query: str, vars: dict[str, Any]) -> Any: ...


Progress = Callable[[int, int], Awaitable[None]]


async def sync_source(
    db: Database,
    source_id: RecordID,
    *,
    allowed_roots: list[str],
    data_roots: list[str],
    progress: Progress | None = None,
    incremental: bool = True,
) -> dict[str, Any]:
    """Stage a source and activate it only after all writes succeed.

    Subsequent wiki and search builds remain separate jobs.
    """
    if source_id.table_name != "repo_source":
        raise ValueError("Expected a repo_source record")
    source = await db.query("SELECT * FROM ONLY $id;", {"id": source_id})
    if not isinstance(source, dict) or not source.get("enabled"):
        raise ValueError("Source is missing or disabled")
    lock = await acquire(db.query_raw, source["kb"])
    try:
        current = await db.query("SELECT * FROM ONLY $id;", {"id": source_id})
        if (
            not isinstance(current, dict)
            or not current.get("enabled")
            or current.get("kb") != lock.kb
        ):
            raise ValueError("Source changed before sync")
        return await _sync_locked(
            db,
            source_id,
            current,
            lock,
            allowed_roots,
            data_roots,
            progress,
            incremental,
        )
    finally:
        await release(db.query_raw, lock)


async def _sync_locked(
    db: Database,
    source_id: RecordID,
    source: dict[str, Any],
    lock: WriteLock,
    allowed_roots: list[str],
    data_roots: list[str],
    progress: Progress | None,
    incremental: bool,
) -> dict[str, Any]:
    path = validate_source_path(
        source["path"], allowed_roots=allowed_roots, data_roots=data_roots
    )
    protected = [ProtectedRule(**rule) for rule in source.get("protected", [])]
    rules = NativePathRules(
        source.get("include", []), source.get("exclude", []), protected
    )
    git = GitRepo(str(path), protected)
    try:
        commit = await asyncio.to_thread(git.head)
        snapshot = await create_snapshot(db.query_raw, source_id, commit, lock)
        entries = await asyncio.to_thread(
            lambda: list(git.walk(commit, rules.allows_dir, rules.allows_file))
        )
        old_files: dict[str, dict[str, Any]] = {}
        if incremental and source.get("current_snapshot"):
            rows = await db.query(
                "SELECT * FROM repo_file WHERE source = $source AND snapshot = $snapshot;",
                {"source": source_id, "snapshot": source["current_snapshot"]},
            )
            if not isinstance(rows, list):
                raise RuntimeError("Unable to read previous source snapshot")
            old_files = {
                row["path"]: row for row in rows if rules.allows_file(row["path"])
            }
        categories: Counter[str] = Counter()
        masks: Counter[str] = Counter()
        reused = 0
        added = 0
        modified = 0
        seen_paths: set[str] = set()
        with tempfile.TemporaryDirectory(prefix="repo-kb-convert-") as tmp:
            for index, entry in enumerate(entries, 1):
                seen_paths.add(entry.path)
                old = old_files.get(entry.path)
                if old and old["blob"] == entry.blob:
                    chunks = await db.query(
                        "SELECT * FROM repo_chunk WHERE file = $file ORDER BY start_line;",
                        {"file": old["id"]},
                    )
                    if not isinstance(chunks, list):
                        raise RuntimeError("Unable to read previous source chunks")
                    prepared = PreparedFile(
                        entry.path,
                        entry.blob,
                        old["category"],
                        old.get("module"),
                        old["method"],
                        old["lines"],
                        old.get("masks", {}),
                        [
                            PreparedChunk(
                                row["start_line"], row["end_line"], row["body"]
                            )
                            for row in chunks
                        ],
                    )
                    reused += 1
                else:
                    if old:
                        modified += 1
                    else:
                        added += 1
                    prepared = await asyncio.to_thread(
                        prepare_entry, git, entry, source["role"], protected, tmp
                    )
                await replace_file(db.query_raw, source_id, snapshot, prepared, lock)
                categories[prepared.category] += 1
                masks.update(prepared.masks)
                if progress is not None:
                    await progress(index, len(entries))
        await activate_snapshot(
            db.query_raw, source_id, snapshot, source["kb"], commit, len(entries), lock
        )
        return {
            "commit": commit,
            "files": len(entries),
            "reused": reused,
            "added": added,
            "modified": modified,
            "deleted": len(set(old_files) - seen_paths),
            "by_category": dict(categories),
            "masks": dict(masks),
        }
    finally:
        await asyncio.to_thread(git.close)
