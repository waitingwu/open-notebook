"""Source path boundaries are checked after resolving symbolic links."""

import subprocess
from pathlib import Path

import pytest

from open_notebook.repo_kb.native_paths import validate_source_path


def test_repo_root_and_realpath_boundaries(tmp_path: Path) -> None:
    root = tmp_path / "allowed"
    root.mkdir()
    repo = root / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    data = tmp_path / "app-data"
    data.mkdir()
    assert (
        validate_source_path(
            str(repo), allowed_roots=[str(root)], data_roots=[str(data)]
        )
        == repo.resolve()
    )
    link = root / "outside"
    link.symlink_to(data, target_is_directory=True)
    with pytest.raises(ValueError):
        validate_source_path(
            str(link), allowed_roots=[str(root)], data_roots=[str(data)]
        )
    with pytest.raises(ValueError):
        validate_source_path(
            str(repo), allowed_roots=[str(root)], data_roots=[str(repo / "data")]
        )
    nested = repo / "nested"
    nested.mkdir()
    with pytest.raises(ValueError):
        validate_source_path(str(nested), allowed_roots=[], data_roots=[])
