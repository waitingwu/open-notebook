"""Path policy for repository ingestion.

Two layers, both enforced before any byte of a file is read:

1. Hard deny (not configurable): any path with a directory component named
   ``usr`` (case-insensitive), plus ``.git``. The tree walker checks this on
   each directory entry *before* descending, so the contents of a denied
   directory are never listed, read, indexed or sent to a model.
2. Per-repo include / exclude globs from the config file.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Iterable, List

HARD_DENY_DIR_NAMES = frozenset({"usr", ".git"})


def is_denied_dir_name(name: str) -> bool:
    return name.lower() in HARD_DENY_DIR_NAMES


def has_denied_component(path: str) -> bool:
    """True if any *directory* component of ``path`` is hard-denied."""
    parts = path.replace("\\", "/").split("/")
    return any(is_denied_dir_name(p) for p in parts[:-1]) or (
        # a bare directory path such as "a/usr" or "usr/"
        path.endswith("/") and is_denied_dir_name(parts[-2] if len(parts) > 1 else "")
    )


def git_exclude_pathspecs() -> List[str]:
    """Pathspecs that keep git commands (log / diff) away from denied dirs."""
    specs = []
    for name in sorted(HARD_DENY_DIR_NAMES - {".git"}):
        specs += [
            f":(exclude,glob,icase)**/{name}/**",
            f":(exclude,glob,icase){name}/**",
        ]
    return specs


def _match_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, p) for p in patterns)


@dataclass
class PathRules:
    include: List[str] = field(default_factory=lambda: ["**"])
    exclude: List[str] = field(default_factory=list)

    def allows_file(self, path: str) -> bool:
        if has_denied_component(path):
            return False
        if self.exclude and _match_any(path, self.exclude):
            return False
        return _match_any(path, self.include) if self.include else True

    def allows_dir(self, dir_path: str) -> bool:
        """Cheap pre-check while walking; a dir is pruned only if excluded."""
        name = dir_path.rstrip("/").rsplit("/", 1)[-1]
        if is_denied_dir_name(name):
            return False
        return not (
            self.exclude and _match_any(dir_path.rstrip("/") + "/", self.exclude)
        )
