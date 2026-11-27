"""Native preparation masks content and never reads protected blobs."""

from unittest.mock import Mock

import pytest

from open_notebook.repo_kb.gitsource import TreeEntry
from open_notebook.repo_kb.native_ingest import prepare_entry
from open_notebook.repo_kb.protected_rules import ProtectedRule


def test_protected_path_rejected_before_read(tmp_path: object) -> None:
    git = Mock()
    with pytest.raises(PermissionError):
        prepare_entry(
            git,
            TreeEntry("secret/file.txt", "blob"),
            "doc",
            [ProtectedRule("dir_name", "secret")],
            str(tmp_path),
        )
    git.read_blob.assert_not_called()


def test_masking_happens_before_chunks_are_returned(tmp_path: object) -> None:
    git = Mock()
    git.read_blob.return_value = b"header\npassword: hidden-value\n192.168.100.8\nend"
    result = prepare_entry(
        git, TreeEntry("docs/a.txt", "blob"), "doc", [], str(tmp_path)
    )
    assert result.lines == 4
    assert result.chunks[0].start_line == 1
    assert result.chunks[0].end_line == 4
    assert "hidden-value" not in result.chunks[0].body
    assert "192.168.100.8" not in result.chunks[0].body
    assert "<SECRET>" in result.chunks[0].body
    assert result.masks["secret"] == 1
