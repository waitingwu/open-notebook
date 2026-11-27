"""Compact, exact candidate generation for the native repo KB keyword index.

The input must already be masked and policy-filtered.  Each snapshot uses
ordinal IDs local to that snapshot; candidates must be verified against the
current authorised source text before they are returned to a user or model.
"""

from __future__ import annotations

import hashlib
import struct
import zlib
from array import array
from collections import defaultdict
from typing import Iterable

from surrealdb import RecordID


def grams(text: str) -> set[str]:
    normalized = text.casefold()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def compile_postings(texts: Iterable[str]) -> tuple[int, dict[str, bytes]]:
    """Generate sorted, compressed 32-bit little-endian document ordinals."""
    postings: dict[str, array] = defaultdict(lambda: array("I"))
    count = 0
    for ordinal, text in enumerate(texts):
        if ordinal >= 2**32:
            raise ValueError("Too many indexed documents")
        for term in grams(text):
            postings[term].append(ordinal)
        count += 1
    encoded = {
        term: zlib.compress(struct.pack(f"<{len(ids)}I", *ids))
        for term, ids in postings.items()
    }
    return count, encoded


def decode_posting(data: bytes, document_count: int) -> set[int]:
    """Reject corrupt or oversized postings before using them."""
    if document_count < 0:
        raise ValueError("Invalid document count")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(data, document_count * 4 + 1)
    except zlib.error as exc:
        raise ValueError("Invalid search posting") from exc
    if (
        not decoder.eof
        or decoder.unused_data
        or len(raw) > document_count * 4
        or len(raw) % 4
    ):
        raise ValueError("Invalid search posting")
    values = {value[0] for value in struct.iter_unpack("<I", raw)}
    if any(value >= document_count for value in values):
        raise ValueError("Invalid search document ordinal")
    return values


def candidates(query: str, postings: dict[str, bytes], document_count: int) -> set[int]:
    """Return a superset of exact matches; short queries require a full scan."""
    terms = grams(query)
    if not terms:
        return set(range(document_count)) if query else set()
    if any(term not in postings for term in terms):
        return set()
    decoded = sorted(
        (decode_posting(postings[term], document_count) for term in terms), key=len
    )
    result = decoded[0]
    for values in decoded[1:]:
        result.intersection_update(values)
    return result


def posting_id(generation: RecordID, term: str) -> RecordID:
    key = hashlib.sha256((str(generation) + "\0" + term).encode("utf-8")).hexdigest()
    return RecordID("repo_search_posting", key)


def document_id(generation: RecordID, ordinal: int) -> RecordID:
    key = hashlib.sha256(
        (str(generation) + "\0" + str(ordinal)).encode("utf-8")
    ).hexdigest()
    return RecordID("repo_search_document", key)
