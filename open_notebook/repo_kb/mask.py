"""Mask infrastructure secrets before text is mirrored, indexed or sent to a model.

Masks are applied line by line, so line numbers in the masked mirror match the
original file and citations stay valid. Only counts per rule are recorded,
never the masked values.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Dict, List, Tuple

_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_H = r"[0-9A-Fa-f]{1,4}"

# (rule name, pattern, replacement); order matters.
_RULES: List[Tuple[str, "re.Pattern[str]", str]] = [
    ("conn", re.compile(r"(?i)\bjdbc:[^\s\"'<>]+"), "<CONN>"),
    (
        "conn",
        re.compile(
            r"(?i)\b(?:data source|server|host|database|initial catalog)\s*=\s*[^;\s\"']+\s*;[^\s\"'<>]*"
        ),
        "<CONN>",
    ),
    (
        "cred_url",
        re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@\"']+:[^/\s@\"']+@"),
        r"\1<CRED>@",
    ),
    # IPv4; outline numbers such as "1.2.3.4\t..." at line start are skipped below
    ("ip", re.compile(rf"(?<![\w.]){_OCTET}(?:\.{_OCTET}){{3}}(?![\w.]|\.\d)"), "<IP>"),
    (
        "ip",
        re.compile(
            rf"(?<![\w:])(?:(?:{_H}:){{7}}{_H}|(?:{_H}:){{1,7}}:(?:{_H}(?::{_H}){{0,6}})?|::(?:{_H}(?::{_H}){{0,6}})?)(?![\w:])"
        ),
        "<IP>",
    ),
    ("email", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL>"),
    (
        "account",
        re.compile(r"(?i)(\bTO\s+(?:USER|GROUP|ROLE)\s+\"?)([A-Za-z0-9_$#@]+)"),
        r"\1<ACCOUNT>",
    ),
    (
        "account",
        re.compile(r"(?i)(\bCONNECT\s+TO\s+\S+\s+USER\s+)(\S+)(\s+USING\s+)(\S+)"),
        r"\1<ACCOUNT>\3<SECRET>",
    ),
]

_SECRET_KEYS = r"password|passwd|pwd|passphrase|secret|api[_-]?key|token|密碼|口令"
_ACCOUNT_KEYS = r"user(?:name|id|_id)?|uid|login|account|帳號|使用者代號|使用者帳號"

# Key = value pairs. In code only quoted literals are masked, so ordinary
# assignments such as ``userId = req.getParameter(...)`` stay readable.
_KV_LITERAL = [
    (
        "secret",
        re.compile(
            rf"(?i)((?<![A-Za-z])(?:{_SECRET_KEYS})\w*\s*[\"']?\s*[:=：(,]\s*)([\"'])([^\"'\n]+)\2"
        ),
        r"\1\2<SECRET>\2",
    ),
    (
        "account",
        re.compile(
            rf"(?i)((?<![A-Za-z])(?:{_ACCOUNT_KEYS})\s*[\"']?\s*[:=：]\s*)([\"'])([^\"'\n]+)\2"
        ),
        r"\1\2<ACCOUNT>\2",
    ),
]
_KV_BARE = [
    (
        "secret",
        re.compile(
            rf"(?i)((?<![A-Za-z])(?:{_SECRET_KEYS})\s*[:=：]\s*)([^\s\"',;<>，。；、）)]+)"
        ),
        r"\1<SECRET>",
    ),
    (
        "account",
        re.compile(
            rf"(?i)((?<![A-Za-z])(?:{_ACCOUNT_KEYS})\s*[:=：]\s*)([^\s\"',;<>，。；、）)]+)"
        ),
        r"\1<ACCOUNT>",
    ),
]

CODE_EXTS = {".java", ".jsp", ".js", ".py", ".sh", ".css", ".tld"}


def _ip_repl(m: "re.Match[str]") -> str:
    octets = [int(x) for x in m.group(0).split(".")]
    at_line_start = not m.string[: m.start()].strip()
    if at_line_start and max(octets) < 32:
        return m.group(0)  # document outline number, e.g. "2.1.3.4"
    return "<IP>"


def mask_text(text: str, is_code: bool = False) -> Tuple[str, Dict[str, int]]:
    counts: Counter = Counter()
    kv = _KV_LITERAL if is_code else _KV_LITERAL + _KV_BARE
    out_lines = []
    for line in text.split("\n"):
        for name, pat, repl in _RULES + kv:
            if name == "ip" and pat is _RULES[3][1]:
                before = line.count("<IP>")
                line = pat.sub(_ip_repl, line)
                n = line.count("<IP>") - before
            else:
                line, n = pat.subn(repl, line)
            if n:
                counts[name] += n
        out_lines.append(line)
    return "\n".join(out_lines), dict(counts)
