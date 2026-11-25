"""Mask secret-shaped substrings before anything reaches the audit log.

Patterns follow Multica's server/pkg/redact (re-implemented, not copied).
"""

import re
from typing import Any, Tuple

_PATTERNS = [
    (
        re.compile(
            r"(?s)-----BEGIN[A-Z\s]*PRIVATE KEY-----.*?-----END[A-Z\s]*PRIVATE KEY-----"
        ),
        "[REDACTED PRIVATE KEY]",
    ),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (
        re.compile(
            r"(?i)(?:aws_secret_access_key|secret_?access_?key)\s*[=:]\s*[A-Za-z0-9/+=]{40}"
        ),
        "[REDACTED AWS SECRET]",
    ),
    (
        re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36,255}\b"),
        "[REDACTED GITHUB TOKEN]",
    ),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,255}\b"), "[REDACTED GITHUB TOKEN]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), "[REDACTED API KEY]"),
    (re.compile(r"\bxox[bporase]-[A-Za-z0-9-]{10,}\b"), "[REDACTED SLACK TOKEN]"),
    (
        re.compile(
            r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
        ),
        "[REDACTED JWT]",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}"), "Bearer [REDACTED]"),
    (
        re.compile(
            r"(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\"?\s*[=:]\s*\"?)[^\s\"',}]{8,}"
        ),
        r"\1[REDACTED]",
    ),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[REDACTED EMAIL]"),
]

ERROR_TAIL_BYTES = 2048


def redact_text(text: str) -> str:
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: redact_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    return value


def tail(text: str, limit: int = ERROR_TAIL_BYTES) -> Tuple[str, bool]:
    """Redact, then keep the last `limit` bytes. Returns (text, truncated)."""
    text = redact_text(text or "")
    data = text.encode("utf-8")
    if len(data) <= limit:
        return text, False
    return data[-limit:].decode("utf-8", errors="ignore"), True
