"""Stage a read-only git source into an atomic native database snapshot."""

from __future__ import annotations

import asyncio
import tempfile
from collections import Counter
from typing import Any, Awaitable, Callable, Protocol

from surrealdb import RecordID

from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.native_db import transaction
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
    file_id,
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
    reserved_lock: WriteLock | None = None,
) -> dict[str, Any]:
    """Stage a source and activate it only after all writes succeed.

    Subsequent wiki and search builds remain separate jobs.
    """
    if source_id.table_name != "repo_source":
        raise ValueError("Expected a repo_source record")
    source = await db.query("SELECT * FROM ONLY $id;", {"id": source_id})
    if not isinstance(source, dict) or not source.get("enabled"):
        raise ValueError("Source is missing or disabled")
    lock = reserved_lock or await acquire(db.query_raw, source["kb"])
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
        if reserved_lock is None:
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
    snapshot = None
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
                    await transaction(
                        db,
                        "CREATE repo_access_log CONTENT $entry;",
                        {
                            "entry": {
                                "source": source_id,
                                "path": entry.path,
                                "blob": entry.blob,
                                "action": "read",
                            }
                        },
                        lock,
                    )
                    prepared = await asyncio.to_thread(
                        prepare_entry, git, entry, source["role"], protected, tmp
                    )
                await replace_file(db.query_raw, source_id, snapshot, prepared, lock)
                categories[prepared.category] += 1
                masks.update(prepared.masks)
                if progress is not None:
                    await progress(index, len(entries))
        history = await asyncio.to_thread(git.last_commits, commit)
        changes = [
            {
                "target": file_id(source_id, snapshot, entry.path),
                "sha": history.get(entry.path, (commit, ""))[0],
                "date": history.get(entry.path, (commit, ""))[1] or None,
            }
            for entry in entries
        ]
        for start in range(0, len(changes), 250):
            await transaction(
                db,
                """FOR $change IN $changes {
                LET $target=$change.target;
                UPDATE $target SET last_commit=$change.sha,last_date=$change.date;
            };""",
                {"changes": changes[start : start + 250]},
                lock,
            )
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
    except BaseException:
        if snapshot is not None:
            try:
                await db.query_raw(
                    """BEGIN TRANSACTION;
                LET $staging = SELECT * FROM ONLY $snapshot;
                IF $staging != NONE AND $staging.source=$source AND $staging.ready=false {
                    DELETE repo_chunk WHERE snapshot=$snapshot;
                    DELETE repo_file WHERE snapshot=$snapshot;
                    DELETE $snapshot;
                };
                COMMIT TRANSACTION;""",
                    {"snapshot": snapshot, "source": source_id},
                )
            except Exception:
                pass  # An unavailable DB cannot expose an unpublished snapshot.
        raise
    finally:
        await asyncio.to_thread(git.close)
