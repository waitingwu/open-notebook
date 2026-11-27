"""Protected exclusions must prune directories before they are opened."""

import pytest

from open_notebook.repo_kb.protected_rules import ProtectedRule, is_protected


def test_rules_are_empty_by_default_and_git_is_always_excluded() -> None:
    assert not is_protected("usr/secret.txt", is_dir=False, rules=[])
    assert is_protected("a/.GIT", is_dir=True, rules=[])
    assert is_protected("a/.git/config", is_dir=False, rules=[])


def test_directory_rules_are_case_insensitive_and_prune_before_descent() -> None:
    rules = [ProtectedRule("dir_name", "usr")]
    assert is_protected("a/USR", is_dir=True, rules=rules)
    assert is_protected("a/USR/file.txt", is_dir=False, rules=rules)
    assert not is_protected("a/usr.txt", is_dir=False, rules=rules)
    assert not is_protected(
        "a/USR", is_dir=True, rules=[ProtectedRule("dir_name", "usr", False)]
    )


def test_glob_prunes_matched_subtree_but_not_other_directories() -> None:
    rules = [ProtectedRule("glob", "CSR2/source/*/secret/**")]
    assert is_protected("CSR2/source/AV/secret", is_dir=True, rules=rules)
    assert is_protected("CSR2/source/AV/secret/nested/x", is_dir=False, rules=rules)
    assert not is_protected("CSR2/source/AV/other/x", is_dir=False, rules=rules)


def test_direct_descendant_lookup_respects_a_pruned_glob_directory() -> None:
    rules = [ProtectedRule("glob", "a/*")]
    assert is_protected("a/private", is_dir=True, rules=rules)
    assert is_protected("a/private/nested/file", is_dir=False, rules=rules)


@pytest.mark.parametrize("pattern", ["", "*", "**", "/", "../secret", "x//y"])
def test_rejects_dangerous_patterns(pattern: str) -> None:
    with pytest.raises(ValueError):
        ProtectedRule("glob", pattern)
