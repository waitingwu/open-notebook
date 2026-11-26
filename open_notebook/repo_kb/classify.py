"""Classify repository files into knowledge layers."""

from __future__ import annotations

import re
from typing import Optional

from open_notebook.repo_kb.extract import ext_of

DIAGRAM = "diagram"  # architecture / UML / flow charts
DDL = "ddl"  # table / view definitions
SPEC = "spec"  # program specs and business rules
SOP = "sop"  # troubleshooting / operation manuals
CODE = "code"  # Java / JSP / JS / shell
APP_SQL = "sql"  # SQL used by programs
OTHER = "other"

_DIAGRAM_EXTS = {".vsd", ".vsdx", ".drawio", ".puml", ".plantuml", ".mmd", ".xmi"}
_SOP_NAME = re.compile(
    r"維運|SOP|問題處理|Q&A|操作手冊|處理流程|排查|錯誤處理|手冊|說明"
)
_SPEC_NAME = re.compile(r"^(UC|UZ)?AV_?[A-Z0-9]{2}|^UC|^UZ", re.I)
_SPEC_DIRS = ("/主程式/", "/批次/", "/模組/", "/共用模組/")
_CREATE = re.compile(r"(?i)\bCREATE\s+(TABLE|VIEW)\b")


def classify(role: str, path: str, text: Optional[str]) -> str:
    ext = ext_of(path)
    name = path.rsplit("/", 1)[-1]
    if ext == ".sql" or ext == ".SQL".lower():
        if text and _CREATE.search(text) and (role == "doc" or "/DB/" in path):
            return DDL
        return APP_SQL
    if role == "src":
        if ext in {".java", ".jsp", ".js", ".sh", ".ksh", ".bat", ".py"}:
            return CODE
        return OTHER
    # documentation repo
    if ext in _DIAGRAM_EXTS or re.search(r"/_docs/0[1-7]_", path) or "流程圖" in name:
        return DIAGRAM
    if "/08_維運手冊/" in path or "/影像系統IT設定流程/" in path:
        return SOP
    if ext in {".doc", ".docx", ".pdf", ".rtf"} and (
        _SPEC_NAME.search(name) or any(d in path for d in _SPEC_DIRS)
    ):
        return SPEC
    if _SOP_NAME.search(name):
        return SOP
    if ext in {".doc", ".docx"}:
        return SPEC
    return OTHER


_MODULE_DIR = re.compile(r"/AV影像系統/([A-Z][0-9A-Z])(?:_|/)")


def module_of(path: str) -> Optional[str]:
    """Two-character AV sub-system code (E0, Z1, ...) if derivable from the path."""
    m = _MODULE_DIR.search(path)
    if m:
        return m.group(1).upper()
    m = re.search(r"/com/cathay/av/([a-z][0-9a-z])/", path)
    if m:
        return m.group(1).upper()
    m = re.search(r"com\.cathay\.av\.([a-z][0-9a-z])\.", path)
    if m:
        return m.group(1).upper()
    m = re.search(r"/AV/([A-Z][0-9A-Z])/", path)
    if m:
        return m.group(1).upper()
    return None
