"""Resolve citations only from masked database snapshots under current policy."""

from __future__ import annotations

from typing import Any

from surrealdb import RecordID

from open_notebook.repo_kb.cite import CITE_RE
from open_notebook.repo_kb.native_access import check_policy_version, source_rules
from open_notebook.repo_kb.native_db import one, query, visible_kb


def citations(text: str) -> list[dict[str, Any]]:
    return [
        {
            "repo": m.group(1),
            "path": m.group(2),
            "start": int(m.group(3)),
            "end": int(m.group(4) or m.group(3)),
            "commit": m.group(5),
            "ref": m.group(0),
        }
        for m in CITE_RE.finditer(text)
    ]


async def resolve(
    db: Any, kb_id: RecordID, ref: str, *, context: int = 5
) -> dict[str, Any]:
    values = citations(ref if ref.startswith("〔") else f"〔{ref}〕")
    if len(values) != 1:
        return {"valid": False, "status": "invalid_format", "ref": ref}
    value = values[0]
    kb = await visible_kb(db, kb_id)
    sources = (
        await query(
            db,
            "SELECT * FROM repo_source WHERE kb=$kb AND name=$name AND enabled=true;",
            {"kb": kb_id, "name": value["repo"]},
        )
        or []
    )
    if not sources:
        return {"valid": False, "status": "unknown_source", "ref": ref}
    source = sources[0]
    path = value["path"]
    if (
        path.startswith("/")
        or ".." in path.split("/")
        or not source_rules(source).allows_file(path)
    ):
        return {"valid": False, "status": "denied_path", "ref": ref}
    rows = (
        await query(
            db,
            "SELECT * FROM repo_file WHERE source=$source AND path=$path;",
            {"source": source["id"], "path": path},
        )
        or []
    )
    snapshots = (
        await query(
            db,
            "SELECT id FROM repo_source_snapshot WHERE source=$source AND ready=true;",
            {"source": source["id"]},
        )
        or []
    )
    ready = {str(row["id"]) for row in snapshots}
    rows = [row for row in rows if str(row["snapshot"]) in ready]
    wanted = value["commit"]
    matches = [
        r
        for r in rows
        if r.get("last_commit")
        and (
            r["last_commit"].startswith(wanted)
            or (wanted == "HEAD" and r["snapshot"] == source.get("current_snapshot"))
        )
    ]
    if not matches:
        return {"valid": False, "status": "unknown_file_or_commit", "ref": ref}
    if len({r["last_commit"] for r in matches}) != 1:
        return {"valid": False, "status": "ambiguous_commit", "ref": ref}
    file = matches[0]
    if not (1 <= value["start"] <= value["end"] <= file["lines"]):
        return {"valid": False, "status": "line_out_of_range", "ref": ref}
    start, end = (
        max(1, value["start"] - context),
        min(file["lines"], value["end"] + context),
    )
    chunks = (
        await query(
            db,
            "SELECT start_line,body FROM repo_chunk WHERE file=$file AND start_line<=$end AND end_line>=$start ORDER BY start_line;",
            {"file": file["id"], "start": start, "end": end},
        )
        or []
    )
    lines = {
        c["start_line"] + i: line
        for c in chunks
        for i, line in enumerate(c["body"].split("\n"))
    }
    await check_policy_version(db, kb_id, kb.get("policy_version", 0))
    latest = await one(db, source["id"], "repo_source")
    if not latest["enabled"] or not source_rules(latest).allows_file(path):
        return {"valid": False, "status": "denied_path", "ref": ref}
    return {
        "valid": True,
        "status": "ok",
        "ref": value["ref"],
        "file_commit": file["last_commit"],
        "stale": file["snapshot"] != latest.get("current_snapshot"),
        "lines": [
            {
                "number": n,
                "text": lines.get(n, ""),
                "highlight": value["start"] <= n <= value["end"],
            }
            for n in range(start, end + 1)
        ],
    }


async def validate(db: Any, kb: RecordID, text: str) -> dict[str, Any]:
    refs = list(dict.fromkeys(c["ref"] for c in citations(text)))
    results = [await resolve(db, kb, ref, context=0) for ref in refs]
    return {
        "total": len(refs),
        "valid": sum(r["valid"] for r in results),
        "invalid": [
            {"ref": r["ref"], "status": r["status"]} for r in results if not r["valid"]
        ],
    }
