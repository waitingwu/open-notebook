"""Validate source repository paths before exposing them to import jobs."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _within(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def validate_source_path(
    path: str, *, allowed_roots: list[str], data_roots: list[str]
) -> Path:
    """Return a canonical git worktree root after checking configured boundaries."""
    try:
        candidate = Path(path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ValueError(
            "Repository path does not exist or cannot be accessed"
        ) from exc
    if not candidate.is_dir():
        raise ValueError("Repository path must be a directory")
    allowlist = [Path(root).expanduser().resolve(strict=True) for root in allowed_roots]
    if allowlist and not any(_within(candidate, root) for root in allowlist):
        raise ValueError("Repository path is outside the allowed roots")
    for data_root in data_roots:
        protected = Path(data_root).expanduser().resolve()
        if _within(candidate, protected) or _within(protected, candidate):
            raise ValueError("Repository path overlaps an application data directory")
    try:
        result = subprocess.run(
            ["git", "-C", str(candidate), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        raise ValueError("Repository path must be a git worktree") from exc
    root = Path(result.stdout.strip()).resolve(strict=True)
    if root != candidate:
        raise ValueError("Select the repository root directory")
    return candidate
