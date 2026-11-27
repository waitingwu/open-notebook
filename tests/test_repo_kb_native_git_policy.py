"""The native git walker must prune user-selected protected trees."""

import subprocess
from pathlib import Path

import pytest

from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.protected_rules import ProtectedRule


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_walk_and_history_prune_configured_directory(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "Test")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    (tmp_path / "public.txt").write_text("public")
    (tmp_path / "secret").mkdir()
    (tmp_path / "secret" / "private.txt").write_text("private")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "fixture")
    reader = GitRepo(str(tmp_path), [ProtectedRule("dir_name", "secret")])
    try:
        head = reader.head()
        assert [
            entry.path for entry in reader.walk(head, lambda _: True, lambda _: True)
        ] == ["public.txt"]
        assert set(reader.last_commits(head)) == {"public.txt"}
        with pytest.raises(PermissionError):
            reader.read_path(head, "secret/private.txt")
    finally:
        reader.close()
