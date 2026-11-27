"""Candidate generation is complete and malformed postings fail closed."""

import zlib

import pytest

from open_notebook.repo_kb.native_search import (
    candidates,
    compile_postings,
    decode_posting,
)


def test_candidates_cover_cjk_identifiers_and_error_codes() -> None:
    texts = ["執行紀錄位置", "select DTAV0011_AA", "DB2 SQLCODE=-803", "not a match"]
    count, index = compile_postings(texts)
    for query, ordinal in [
        ("執行紀錄位置", 0),
        ("dtav0011_aa", 1),
        ("SQLCODE=-803", 2),
    ]:
        assert ordinal in candidates(query, index, count)
    assert candidates("not present", index, count) == set()
    assert candidates("執", index, count) == set(range(count))
    assert candidates("", index, count) == set()


def test_false_positives_require_exact_source_verification() -> None:
    count, index = compile_postings(["abc abd bcd", "abcd"])
    assert candidates("abcd", index, count) == {0, 1}


@pytest.mark.parametrize(
    "value", [b"invalid", zlib.compress(b"abc"), zlib.compress(b"\xff\xff\xff\xff")]
)
def test_corrupt_or_invalid_posting_rejected(value: bytes) -> None:
    with pytest.raises(ValueError):
        decode_posting(value, 1)
