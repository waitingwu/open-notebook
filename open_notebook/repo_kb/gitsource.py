"""Read-only access to a local git repository.

Everything is read from git objects of a fixed commit (never the working tree),
so citations ``path#Lx@commit`` are reproducible and uncommitted local edits
in the source repo are ignored. Nothing here writes to the repository.

The tree walk decodes tree objects itself through one ``git cat-file --batch``
process and checks every directory entry against :mod:`policy` *before*
descending, so a hard-denied directory (``usr``) is never listed.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, Iterator, List, Optional, Tuple

from open_notebook.repo_kb.policy import (
    git_exclude_pathspecs,
    has_denied_component,
    is_denied_dir_name,
)


@dataclass
class TreeEntry:
    path: str
    blob: str
    size: int = 0


class GitRepo:
    def __init__(self, path: str):
        self.path = path
        self._batch: Optional[subprocess.Popen] = None

    # -- plumbing ---------------------------------------------------------
    def _git(self, *args: str) -> bytes:
        return subprocess.run(
            ["git", "-C", self.path, "-c", "core.quotepath=false", *args],
            check=True,
            capture_output=True,
        ).stdout

    def _cat(self, spec: str) -> Tuple[str, bytes]:
        _, otype, data = self._cat_full(spec)
        return otype, data

    def _cat_full(self, spec: str) -> Tuple[str, str, bytes]:
        if self._batch is None:
            self._batch = subprocess.Popen(
                ["git", "-C", self.path, "cat-file", "--batch"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
            )
        assert self._batch.stdin and self._batch.stdout
        self._batch.stdin.write(spec.encode() + b"\n")
        self._batch.stdin.flush()
        header = self._batch.stdout.readline().decode().split()
        if len(header) < 3:
            raise KeyError(f"git object not found: {spec}")
        sha, otype, size = header[0], header[1], int(header[2])
        data = self._batch.stdout.read(size)
        self._batch.stdout.read(1)  # trailing LF
        return sha, otype, data

    def close(self) -> None:
        if self._batch:
            self._batch.kill()
            self._batch.wait()
            self._batch = None

    # -- queries ----------------------------------------------------------
    def head(self) -> str:
        return self._git("rev-parse", "HEAD").decode().strip()

    def resolve(self, rev: str) -> str:
        return self._git("rev-parse", rev).decode().strip()

    def walk(
        self,
        commit: str,
        allow_dir: Callable[[str], bool],
        allow_file: Callable[[str], bool],
    ) -> Iterator[TreeEntry]:
        otype, data = self._cat(f"{commit}^{{tree}}")
        yield from self._walk_tree(data, "", allow_dir, allow_file)

    def _walk_tree(self, data: bytes, prefix: str, allow_dir, allow_file):
        i = 0
        while i < len(data):
            sp = data.index(b" ", i)
            nul = data.index(b"\0", sp)
            mode = data[i:sp].decode()
            name = data[sp + 1 : nul].decode("utf-8", errors="surrogateescape")
            sha = data[nul + 1 : nul + 21].hex()
            i = nul + 21
            path = prefix + name
            if mode == "40000":
                # Policy check BEFORE the sub-tree object is read.
                if is_denied_dir_name(name) or not allow_dir(path + "/"):
                    continue
                _, sub = self._cat(sha)
                yield from self._walk_tree(sub, path + "/", allow_dir, allow_file)
            elif mode.startswith("100"):
                if has_denied_component(path) or not allow_file(path):
                    continue
                yield TreeEntry(path=path, blob=sha)
            # submodules (160000) and symlinks (120000) are skipped

    def read_blob(self, blob: str) -> bytes:
        otype, data = self._cat(blob)
        if otype != "blob":
            raise ValueError(f"{blob} is a {otype}")
        return data

    def read_path(self, commit: str, path: str) -> Tuple[str, bytes]:
        """(blob sha, content) of ``path`` at ``commit``; policy-checked."""
        if has_denied_component(path):
            raise PermissionError(f"path denied by policy: {path}")
        sha, otype, data = self._cat_full(f"{commit}:{path}")
        if otype != "blob":
            raise ValueError(f"{path} is a {otype}")
        return sha, data

    def last_commits(self, commit: str) -> Dict[str, Tuple[str, str]]:
        """path -> (commit sha, ISO commit date) of the last change, one log pass."""
        out = self._git(
            "log",
            commit,
            "--format=%x01%H%x09%cI",
            "--name-only",
            "--no-renames",
            "--",
            ".",
            *git_exclude_pathspecs(),
        ).decode("utf-8", errors="surrogateescape")
        result: Dict[str, Tuple[str, str]] = {}
        cur: Optional[Tuple[str, str]] = None
        for line in out.splitlines():
            if line.startswith("\x01"):
                sha, date = line[1:].split("\t")
                cur = (sha, date)
            elif line and cur and line not in result and not has_denied_component(line):
                result[line] = cur
        return result

    def blob_at(self, commit: str, path: str) -> Optional[str]:
        if has_denied_component(path):
            raise PermissionError(f"path denied by policy: {path}")
        out = subprocess.run(
            [
                "git",
                "-C",
                self.path,
                "rev-parse",
                "--verify",
                "-q",
                f"{commit}^{{commit}}:{path}",
            ],
            capture_output=True,
            text=True,
        )
        return out.stdout.strip() if out.returncode == 0 else None

    def last_commit_of(self, commit: str, path: str) -> Tuple[str, str]:
        if has_denied_component(path):
            raise PermissionError(f"path denied by policy: {path}")
        out = (
            self._git("log", "-1", "--format=%H%x09%cI", commit, "--", path)
            .decode()
            .strip()
        )
        sha, date = out.split("\t")
        return sha, date

    def diff(self, old: str, new: str) -> List[Tuple[str, str]]:
        """[(status, path)] between two commits, denied dirs excluded."""
        out = self._git(
            "diff",
            "--name-status",
            "--no-renames",
            old,
            new,
            "--",
            ".",
            *git_exclude_pathspecs(),
        ).decode("utf-8", errors="surrogateescape")
        changes = []
        for line in out.splitlines():
            status, path = line.split("\t", 1)
            if not has_denied_component(path):
                changes.append((status[0], path))
        return changes
