"""Prepare a git blob for native persistence without storing unmasked text."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from open_notebook.repo_kb.classify import classify, module_of
from open_notebook.repo_kb.extract import ext_of, extract
from open_notebook.repo_kb.gitsource import GitRepo, TreeEntry
from open_notebook.repo_kb.mask import CODE_EXTS, mask_text
from open_notebook.repo_kb.protected_rules import ProtectedRule, is_protected

CHUNK_LINES = 40


@dataclass(frozen=True)
class PreparedChunk:
    start_line: int
    end_line: int
    body: str


@dataclass(frozen=True)
class PreparedFile:
    path: str
    blob: str
    category: str
    module: Optional[str]
    method: str
    lines: int
    masks: dict[str, int]
    chunks: list[PreparedChunk]


def prepare_entry(
    git: GitRepo,
    entry: TreeEntry,
    role: str,
    rules: list[ProtectedRule],
    tmpdir: str,
) -> PreparedFile:
    """Check policy before blob access, then extract and mask before chunking."""
    if is_protected(entry.path, is_dir=False, rules=rules):
        raise PermissionError("Protected source path")
    text, method = extract(entry.path, git.read_blob(entry.blob), tmpdir)
    masks: dict[str, int] = {}
    if text is not None:
        text, masks = mask_text(text, is_code=ext_of(entry.path) in CODE_EXTS)
    category = classify(role, entry.path, text)
    lines = text.split("\n") if text is not None else []
    chunks = []
    for offset in range(0, len(lines), CHUNK_LINES):
        body = "\n".join(lines[offset : offset + CHUNK_LINES])
        if body.strip():
            chunks.append(
                PreparedChunk(offset + 1, min(offset + CHUNK_LINES, len(lines)), body)
            )
    return PreparedFile(
        path=entry.path,
        blob=entry.blob,
        category=category,
        module=module_of(entry.path),
        method=method,
        lines=len(lines),
        masks=masks,
        chunks=chunks,
    )
