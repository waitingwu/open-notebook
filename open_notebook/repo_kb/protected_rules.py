"""Configurable protected exclusions for native repo KB sources.

Callers must test directory entries before opening their trees.  These rules
are intentionally independent of the PoC's fixed policy during migration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ProtectedRule:
    kind: Literal["dir_name", "glob"]
    pattern: str
    enabled: bool = True

    def __post_init__(self) -> None:
        pattern = self.pattern
        if not pattern or pattern in {"*", "**", "/"}:
            raise ValueError("Protected exclusion must not match the whole source")
        if self.kind not in {"dir_name", "glob"}:
            raise ValueError("Unknown protected exclusion kind")
        if (
            pattern.startswith("/")
            or "\\" in pattern
            or any(part in {"", ".", ".."} for part in pattern.split("/"))
        ):
            raise ValueError("Protected exclusion must be a relative path")
        if self.kind == "dir_name" and (
            "/" in pattern or any(c in pattern for c in "*?[]")
        ):
            raise ValueError("Directory name must be a literal name")


def _glob_regex(pattern: str) -> re.Pattern[str]:
    parts: list[str] = []
    i = 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern[i : i + 3] == "**/":
            parts.append("(?:.*/)?")
            i += 3
        elif pattern[i : i + 2] == "**":
            parts.append(".*")
            i += 2
        elif ch == "*":
            parts.append("[^/]*")
            i += 1
        elif ch == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(ch))
            i += 1
    return re.compile("".join(parts), re.IGNORECASE)


def is_protected(path: str, *, is_dir: bool, rules: list[ProtectedRule]) -> bool:
    """Return whether a path is excluded; .git is always pruned."""
    normalized = path.replace("\\", "/").strip("/")
    components = normalized.split("/") if normalized else []
    directories = components if is_dir else components[:-1]
    if any(part.casefold() == ".git" for part in directories):
        return True
    for rule in rules:
        if not rule.enabled:
            continue
        if rule.kind == "dir_name":
            if any(part.casefold() == rule.pattern.casefold() for part in directories):
                return True
            continue
        regex = _glob_regex(rule.pattern)
        if regex.fullmatch(normalized):
            return True
        # Later reads and citation checks must also honour previously pruned
        # directories, even if they receive a descendant path directly.
        if any(
            regex.fullmatch("/".join(directories[:i]))
            for i in range(1, len(directories) + 1)
        ):
            return True
        # A pattern ending in /** protects the directory itself before descent.
        if rule.pattern.endswith("/**"):
            parent = _glob_regex(rule.pattern[:-3])
            for i in range(1, len(directories) + 1):
                if parent.fullmatch("/".join(directories[:i])):
                    return True
    return False
