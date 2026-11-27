"""Deterministic parsers: DDL tables, program specs, and code table usage."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

# --------------------------------------------------------------------------
# DDL
# --------------------------------------------------------------------------

_IDENT = r'"?\s*([A-Za-z0-9_#$@]+)\s*"?'
_CREATE_RE = re.compile(rf"(?i)\bCREATE\s+(TABLE|VIEW)\s+(?:{_IDENT}\s*\.\s*)?{_IDENT}")
_COL_RE = re.compile(
    r'^\s*"?([A-Za-z0-9_#$@]+)"?\s+([A-Za-z]+(?:\s*\([0-9, ]+\))?)(.*)$'
)
_PK_RE = re.compile(r"(?is)PRIMARY\s+KEY\s*\(([^)]*)\)")
_FK_RE = re.compile(
    r"(?is)FOREIGN\s+KEY\s*\(([^)]*)\)\s*REFERENCES\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s*\(([^)]*)\)"
)
_INDEX_RE = re.compile(
    r"(?is)CREATE\s+(UNIQUE\s+)?INDEX\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s+ON\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s*\(([^)]*)\)"
)
_TCOMMENT_RE = re.compile(
    r"(?is)COMMENT\s+ON\s+TABLE\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s+IS\s+'([^']*)'"
)
_CCOMMENT_RE = re.compile(
    r"(?is)COMMENT\s+ON\s+COLUMN\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s*\.\s*\"?(\w+)\"?\s+IS\s+'([^']*)'"
)
_LABEL_RE = re.compile(
    r"(?is)LABEL\s+ON\s+COLUMN\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?\s*\.\s*\"?(\w+)\"?\s+IS\s+'([^']*)'"
)
_COL_SKIP = {
    "PRIMARY",
    "CONSTRAINT",
    "FOREIGN",
    "UNIQUE",
    "CHECK",
    "IN",
    "INDEX",
    "PARTITION",
    "DISTRIBUTE",
}


def _cols(s: str) -> List[str]:
    return [c.strip().strip('"').split()[0] for c in s.split(",") if c.strip()]


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1


@dataclass
class Column:
    name: str
    type: str
    nullable: bool
    default: Optional[str]
    comment: str = ""
    line: int = 0


@dataclass
class Table:
    name: str
    kind: str
    schema: str
    path: str
    line: int
    columns: List[Column] = field(default_factory=list)
    pk: List[str] = field(default_factory=list)
    fks: List[Tuple[List[str], str, List[str]]] = field(default_factory=list)
    indexes: List[Tuple[str, bool, List[str]]] = field(default_factory=list)
    comment: str = ""
    comment_line: int = 0


def parse_ddl(text: str, path: str) -> List[Table]:
    tables: Dict[str, Table] = {}
    for m in _CREATE_RE.finditer(text):
        kind = m.group(1).upper()
        schema, name = (m.group(2) or "").strip(), m.group(3).strip()
        if name.upper() in {"OR", "REPLACE"}:
            continue
        t = Table(
            name=name.upper(),
            kind=kind,
            schema=schema.upper(),
            path=path,
            line=_line_of(text, m.start()),
        )
        if kind == "TABLE":
            # column block: from first "(" after the name to the matching ")"
            start = text.find("(", m.end())
            depth, i = 0, start
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            block = text[start + 1 : i]
            offset = start + 1
            for raw in re.split(r",\s*\n|\n", block):
                cm = _COL_RE.match(raw)
                if not cm or cm.group(1).upper() in _COL_SKIP:
                    continue
                rest = cm.group(3)
                d = re.search(r"(?i)DEFAULT\s+('[^']*'|[^\s,]+)", rest)
                pos = text.find(raw.strip(), offset)
                t.columns.append(
                    Column(
                        name=cm.group(1).upper(),
                        type=re.sub(r"\s+", "", cm.group(2).upper()),
                        nullable="NOT NULL" not in rest.upper(),
                        default=d.group(1) if d else None,
                        line=_line_of(text, pos) if pos >= 0 else t.line,
                    )
                )
            pk = _PK_RE.search(block)
            if pk:
                t.pk = [c.upper() for c in _cols(pk.group(1))]
        tables[t.name] = t
    if not tables:
        return []
    for m in _PK_RE.finditer(text):
        # ALTER TABLE ... ADD CONSTRAINT ... PRIMARY KEY
        before = text[max(0, m.start() - 300) : m.start()]
        at = re.findall(
            r"(?i)ALTER\s+TABLE\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?", before
        )
        if at and at[-1].upper() in tables and not tables[at[-1].upper()].pk:
            tables[at[-1].upper()].pk = [c.upper() for c in _cols(m.group(1))]
    for m in _FK_RE.finditer(text):
        before = text[max(0, m.start() - 300) : m.start()]
        at = re.findall(
            r"(?i)(?:ALTER\s+TABLE|CREATE\s+TABLE)\s+(?:\"?\w+\"?\s*\.\s*)?\"?(\w+)\"?",
            before,
        )
        if at and at[-1].upper() in tables:
            tables[at[-1].upper()].fks.append(
                (
                    [c.upper() for c in _cols(m.group(1))],
                    m.group(2).upper(),
                    [c.upper() for c in _cols(m.group(3))],
                )
            )
    for m in _INDEX_RE.finditer(text):
        tn = m.group(3).upper()
        if tn in tables:
            tables[tn].indexes.append(
                (m.group(2).upper(), bool(m.group(1)), _cols(m.group(4)))
            )
    for m in _TCOMMENT_RE.finditer(text):
        if m.group(1).upper() in tables:
            tables[m.group(1).upper()].comment = m.group(2).strip()
            tables[m.group(1).upper()].comment_line = _line_of(text, m.start())
    for rx in (_CCOMMENT_RE, _LABEL_RE):
        for m in rx.finditer(text):
            tc = tables.get(m.group(1).upper())
            if tc:
                for c in tc.columns:
                    if c.name == m.group(2).upper() and not c.comment:
                        c.comment = m.group(3).strip()
    return list(tables.values())


# --------------------------------------------------------------------------
# Program spec documents (UC / UZ templates)
# --------------------------------------------------------------------------

_BOX = re.compile(r"^[■□]$")
_TABLE_TOKEN = re.compile(r"^[A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)*$")
_PROG_TOKEN = re.compile(r"([A-Za-z][A-Za-z0-9_.]*[A-Za-z0-9])")


@dataclass
class SpecTable:
    name: str
    desc: str
    crud: str  # subset of "RCUD"
    line: int


@dataclass
class Spec:
    path: str
    program: Optional[str] = None
    program_line: int = 0
    title: str = ""
    mode: str = ""
    summary: str = ""
    summary_line: int = 0
    tables: List[SpecTable] = field(default_factory=list)
    tables_line: int = 0
    modules: List[Tuple[str, str, int]] = field(default_factory=list)


def normalize_program(token: str) -> str:
    """AVZ1_2000.java → AVZ1_2000; UZAV_Z1Z001 → AV_Z1Z001; UCAVZ1_B100 → AVZ1_B100."""
    t = token.strip()
    t = re.sub(r"\.(java|jsp|class)$", "", t, flags=re.I)
    t = t.rsplit(".", 1)[-1] if "." in t else t
    t = re.sub(r"^UZ(AV_)", r"\1", t, flags=re.I)
    t = re.sub(r"^UC(AV)", r"\1", t, flags=re.I)
    return t.upper()


def program_from_filename(path: str) -> Optional[str]:
    name = path.rsplit("/", 1)[-1]
    m = re.match(
        r"(?i)(UZAV_[A-Z0-9]+|UCAV[A-Z0-9]{2}_[A-Z0-9]+|AV[A-Z0-9]{2}_[A-Z0-9]+|AV_[A-Z0-9]+)",
        name,
    )
    return normalize_program(m.group(1)) if m else None


def parse_spec(text: str, path: str) -> Spec:
    lines = [ln.strip() for ln in text.split("\n")]
    spec = Spec(path=path)

    def next_value(i: int) -> Tuple[str, int]:
        for j in range(i + 1, min(i + 6, len(lines))):
            if lines[j]:
                return lines[j], j + 1
        return "", 0

    section = None
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln in ("程式名稱", "模組ID") and not spec.program:
            v, n = next_value(i)
            m = _PROG_TOKEN.search(v)
            if m:
                spec.program, spec.program_line = normalize_program(m.group(1)), n
        elif ln in ("程式功能", "模組名稱") and not spec.title:
            spec.title, _ = next_value(i)
        elif ln == "作業方式" and not spec.mode:
            spec.mode, _ = next_value(i)
        elif ln == "概要說明" and not spec.summary:
            buf, j = [], i + 1
            while j < len(lines) and lines[j] not in (
                "需求單位",
                "作業單位",
                "作業平台",
            ):
                if lines[j]:
                    buf.append(lines[j])
                j += 1
            spec.summary, spec.summary_line = " ".join(buf)[:600], i + 2
        if re.search(r"相關檔案$", ln):
            section, spec.tables_line = "files", i + 1
        elif re.search(r"相關模組$", ln):
            section = "modules"
        elif section and re.match(r"^(•\s*\S|[一二三四五六七八九十]+、)", ln):
            section = None  # next numbered heading ends the section
        elif section == "files" and _TABLE_TOKEN.match(ln) and ln not in ("DB", "SQL"):
            desc = ""
            boxes: List[str] = []
            j = i - 1
            if (
                j >= 0
                and lines[j]
                and not _BOX.match(lines[j])
                and not lines[j].startswith(("•", "項次"))
                and not re.match(r"^\d+\.?$", lines[j])
            ):
                desc = lines[j]
            k = i + 1
            while k < len(lines) and len(boxes) < 4 and k < i + 8:
                if _BOX.match(lines[k]):
                    boxes.append(lines[k])
                elif lines[k] and not desc:
                    desc = lines[k]
                k += 1
            if len(boxes) == 4:
                crud = "".join(op for op, b in zip("RCUD", boxes) if b == "■")
                spec.tables.append(SpecTable(name=ln, desc=desc, crud=crud, line=i + 1))
        elif section == "modules":
            m = re.match(r"^([A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*)$", ln)
            if m and ("_" in ln or "." in ln) and ln not in ("程式名稱",):
                desc = lines[i - 1] if i > 0 else ""
                spec.modules.append((ln, desc, i + 1))
        i += 1
    return spec


# --------------------------------------------------------------------------
# Code usage
# --------------------------------------------------------------------------

_SQL_OPS = [
    ("C", re.compile(r"(?is)\bINSERT\s+INTO\s+(?:\w+\s*\.\s*)?([A-Z][A-Z0-9_]+)")),
    (
        "U",
        re.compile(
            r"(?is)\bUPDATE\s+(?:\w+\s*\.\s*)?([A-Z][A-Z0-9_]+)\s+(?:\w+\s+)?SET\b"
        ),
    ),
    ("D", re.compile(r"(?is)\bDELETE\s+FROM\s+(?:\w+\s*\.\s*)?([A-Z][A-Z0-9_]+)")),
    ("R", re.compile(r"(?is)\b(?:FROM|JOIN)\s+(?:\w+\s*\.\s*)?([A-Z][A-Z0-9_]+)")),
]
_TABLEISH = re.compile(
    r"(?<![A-Za-z0-9_])(D[TV][A-Z]{2}[A-Z0-9_]*[0-9][A-Z0-9_]*)(?![A-Za-z0-9_])"
)


def strip_java_comments(src: str) -> str:
    """Blank out comments but keep newlines so line numbers survive."""

    def blank(m: "re.Match[str]") -> str:
        return re.sub(r"[^\n]", " ", m.group(0))

    return re.sub(r"(?s)/\*.*?\*/|//[^\n]*", blank, src)


def sql_usage(sql: str, known: Set[str]) -> Dict[str, Set[str]]:
    out: Dict[str, Set[str]] = {}
    upper = sql.upper()
    claimed: Set[Tuple[int, int]] = set()
    for op, rx in _SQL_OPS:
        for m in rx.finditer(upper):
            name = m.group(1)
            if op == "R" and m.span(1) in claimed:
                continue
            if name in known or _TABLEISH.fullmatch(name):
                out.setdefault(name, set()).add(op)
                claimed.add(m.span(1))
    return out


def java_refs(src: str, known: Set[str]) -> Dict[str, int]:
    """Table names referenced in non-comment Java code → first line number."""
    code = strip_java_comments(src)
    refs: Dict[str, int] = {}
    for m in _TABLEISH.finditer(code):
        name = m.group(1)
        if name in known and name not in refs:
            refs[name] = _line_of(code, m.start())
    return refs


_CALL_RE = re.compile(
    r"\b(AV_[A-Z0-9]+Z[0-9A-Z]+(?:_[A-Za-z0-9]+)?|AV[A-Z0-9]{2}_[A-Z0-9]+(?:_mod)?)\b"
)


def java_calls(src: str, self_name: str) -> Set[str]:
    code = strip_java_comments(src)
    return {c for c in _CALL_RE.findall(code) if c != self_name}
