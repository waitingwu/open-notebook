"""Preview git tree metadata and browse directories without reading blobs."""

from __future__ import annotations

import asyncio
import os
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from open_notebook.exceptions import InvalidInputError
from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.native_access import source_rules
from open_notebook.repo_kb.native_db import query
from open_notebook.repo_kb.native_paths import validate_source_path
from open_notebook.repo_kb.protected_rules import is_protected


def _preview(
    source: dict[str, Any], roots: list[str], data: list[str]
) -> dict[str, Any]:
    path = validate_source_path(source["path"], allowed_roots=roots, data_roots=data)
    rules = source_rules(source)
    blocked = [0] * len(rules.protected)
    excluded = 0
    extensions: Counter[str] = Counter()

    def allow_dir(value: str) -> bool:
        for index, rule in enumerate(rules.protected):
            if is_protected(value, is_dir=True, rules=[rule]):
                blocked[index] += 1
                return False
        return rules.allows_dir(value)

    def allow_file(value: str) -> bool:
        nonlocal excluded
        if not rules.allows_file(value):
            excluded += 1
            return False
        return True

    reader = GitRepo(str(path), [])
    try:
        commit = reader.head()
        entries = list(reader.walk(commit, allow_dir, allow_file))
        for entry in entries:
            extensions[Path(entry.path).suffix.lower() or "(none)"] += 1
        return {
            "commit": commit,
            "files": len(entries),
            "by_extension": dict(extensions),
            "excluded_files": excluded,
            "protected_directories": [
                {"pattern": r.pattern, "count": blocked[i]}
                for i, r in enumerate(rules.protected)
            ],
            "warnings": ["No files match the current rules"] if not entries else [],
        }
    finally:
        reader.close()


async def preview(
    source: dict[str, Any], roots: list[str], data: list[str]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_preview, source, roots, data)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise InvalidInputError("Unable to preview this git repository") from exc


async def browse(
    db: Any, path: str, roots: list[str], data: list[str]
) -> dict[str, Any]:
    base = Path(path).expanduser().resolve(strict=True)
    allowed = [Path(r).expanduser().resolve() for r in roots]
    sources = await query(db, "SELECT * FROM repo_source;") or []

    def permitted(candidate: Path) -> bool:
        actual = candidate.resolve()
        if allowed and not any(actual == r or r in actual.parents for r in allowed):
            return False
        if any(actual == Path(r) or Path(r) in actual.parents for r in data):
            return False
        for source in sources:
            root = Path(source["path"]).resolve()
            if root in actual.parents and not source_rules(source).allows_dir(
                actual.relative_to(root).as_posix() + "/"
            ):
                return False
        return True

    if not permitted(base):
        raise InvalidInputError("Directory is outside the allowed or readable roots")

    def listing() -> list[dict[str, Any]]:
        rows = []
        with os.scandir(base) as entries:
            for entry in entries:
                if entry.name == ".git" or not entry.is_dir(follow_symlinks=False):
                    continue
                candidate = Path(entry.path)
                if permitted(candidate):
                    rows.append(
                        {
                            "name": entry.name,
                            "path": str(candidate),
                            "is_git_repo": (candidate / ".git").exists(),
                        }
                    )
        return sorted(rows, key=lambda row: row["name"].casefold())

    return {
        "path": str(base),
        "parent": str(base.parent) if permitted(base.parent) else None,
        "directories": await asyncio.to_thread(listing),
    }
