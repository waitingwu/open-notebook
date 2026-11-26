"""Turn a blob into plain text (or report that the format is unsupported)."""

from __future__ import annotations

import io
import os
import re
import subprocess
import tempfile
import zipfile
from email import policy as email_policy
from email.parser import BytesParser
from typing import Optional, Tuple

TEXT_EXTS = {
    ".sql",
    ".java",
    ".jsp",
    ".js",
    ".txt",
    ".md",
    ".xml",
    ".properties",
    ".sh",
    ".htm",
    ".html",
    ".css",
    ".tld",
    ".pep",
    ".ini",
    ".py",
    ".csv",
    ".bat",
    ".ksh",
    ".cfg",
    ".conf",
    ".yaml",
    ".yml",
    ".mmd",
    ".puml",
    ".plantuml",
    ".drawio",
    ".xmi",
    ".example",
    ".dtd",
}
TEXTUTIL_EXTS = {".doc", ".docx", ".rtf", ".odt"}
MAX_TEXT_BYTES = 5 * 1024 * 1024


def ext_of(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    m = re.search(r"(\.[A-Za-z0-9]+)(?:\(.*\))?$", base)
    return m.group(1).lower() if m else ""


def decode_bytes(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    for enc in ("utf-8", "cp950", "big5hkscs"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("cp950", errors="replace")


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _textutil(data: bytes, ext: str, tmpdir: str) -> str:
    fd, path = tempfile.mkstemp(suffix=ext, dir=tmpdir)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        out = subprocess.run(
            ["textutil", "-convert", "txt", "-stdout", path],
            capture_output=True,
            timeout=120,
        )
        if out.returncode != 0:
            raise ValueError("textutil failed")
        return out.stdout.decode("utf-8", errors="replace")
    finally:
        os.unlink(path)


def _xlsx(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    lines = []
    for ws in wb.worksheets:
        lines.append(f"## 工作表：{ws.title}")
        for row in ws.iter_rows(values_only=True):
            cells = ["" if v is None else str(v).replace("\n", " ") for v in row]
            if any(cells):
                lines.append(" | ".join(cells).rstrip(" |"))
    return "\n".join(lines)


def _vsdx(data: bytes) -> str:
    """Visio XML: shape texts and connector endpoints, page by page."""
    lines = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        pages = sorted(
            n for n in z.namelist() if re.match(r"visio/pages/page\d+\.xml$", n)
        )
        for name in pages:
            xml = z.read(name).decode("utf-8", errors="replace")
            lines.append(f"## 頁面 {name.rsplit('/', 1)[-1]}")
            for t in re.findall(r"<Text>(.*?)</Text>", xml, flags=re.S):
                t = re.sub(r"<[^>]+>", "", t).strip()
                if t:
                    lines.append("- " + re.sub(r"\s+", " ", t))
    return "\n".join(lines)


def _mht(data: bytes) -> str:
    msg = BytesParser(policy=email_policy.default).parsebytes(data)
    for part in msg.walk():
        if part.get_content_type() in ("text/html", "text/plain"):
            text = part.get_content()
            text = re.sub(r"(?s)<(script|style).*?</\1>", "", text)
            text = re.sub(r"<br\s*/?>|</p>|</tr>|</div>", "\n", text, flags=re.I)
            text = re.sub(r"<[^>]+>", " ", text)
            return re.sub(r"[ \t]+", " ", text)
    return ""


def _pdf(data: bytes) -> str:
    import pdfplumber

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((p.extract_text() or "") for p in pdf.pages[:200])


def extract(path: str, data: bytes, tmpdir: str) -> Tuple[Optional[str], str]:
    """Return (text or None, method). ``None`` means unsupported/binary."""
    ext = ext_of(path)
    try:
        if ext in TEXT_EXTS:
            if (
                len(data) > MAX_TEXT_BYTES
                or b"\0" in data[:4096]
                and not data.startswith((b"\xff\xfe", b"\xfe\xff"))
            ):
                return None, "binary_or_too_large"
            return _normalize(decode_bytes(data)), "text"
        if ext in TEXTUTIL_EXTS:
            return _normalize(_textutil(data, ext, tmpdir)), "textutil"
        if ext == ".xlsx":
            return _normalize(_xlsx(data)), "openpyxl"
        if ext == ".vsdx":
            return _normalize(_vsdx(data)), "vsdx_xml"
        if ext in (".mht", ".mhtml"):
            return _normalize(_mht(data)), "mime_html"
        if ext == ".pdf":
            return _normalize(_pdf(data)), "pdfplumber"
    except Exception as e:  # extraction failure is recorded, not fatal
        return None, f"error:{type(e).__name__}"
    return None, f"unsupported:{ext or 'none'}"
