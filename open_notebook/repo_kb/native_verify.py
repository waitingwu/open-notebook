"""Metadata-only exclusion evidence; this does not open source files."""

from __future__ import annotations

from typing import Any

from surrealdb import RecordID

from open_notebook.repo_kb.native_db import query
from open_notebook.repo_kb.protected_rules import ProtectedRule, is_protected


async def verify_exclusions(db: Any, kb: RecordID) -> dict[str, Any]:
    sources = (
        await query(db, "SELECT * FROM repo_source WHERE kb=$kb;", {"kb": kb}) or []
    )
    reports = []
    pages = (
        await query(
            db, "SELECT citations FROM repo_wiki_page WHERE kb=$kb;", {"kb": kb}
        )
        or []
    )
    events = (
        await query(
            db,
            "SELECT detail FROM repo_kb_event WHERE kb=$kb AND (action='retrieve' OR action='ai_input');",
            {"kb": kb},
        )
        or []
    )
    for source in sources:
        files = (
            await query(
                db, "SELECT path FROM repo_file WHERE source=$id;", {"id": source["id"]}
            )
            or []
        )
        chunks = (
            await query(
                db,
                "SELECT path FROM repo_chunk WHERE source=$id;",
                {"id": source["id"]},
            )
            or []
        )
        logs = (
            await query(
                db,
                "SELECT path FROM repo_access_log WHERE source=$id;",
                {"id": source["id"]},
            )
            or []
        )
        for value in source.get("protected", []):
            rule = ProtectedRule(**value)
            if not rule.enabled:
                continue

            def matched(rows: list[dict[str, Any]]) -> int:
                return sum(
                    is_protected(row["path"], is_dir=False, rules=[rule])
                    for row in rows
                )

            sample = (
                f"probe/{rule.pattern}/example.txt"
                if rule.kind == "dir_name"
                else rule.pattern.replace("**", "probe")
                .replace("*", "sample")
                .replace("?", "x")
            )
            reports.append(
                {
                    "source": str(source["id"]),
                    "source_name": source["name"],
                    "pattern": rule.pattern,
                    "kind": rule.kind,
                    "stored_files": matched(files),
                    "stored_chunks": matched(chunks),
                    "historical_accesses": matched(logs),
                    "wiki_references": sum(
                        c.get("repo") == source["name"]
                        and is_protected(c.get("path", ""), is_dir=False, rules=[rule])
                        for p in pages
                        for c in p.get("citations", [])
                    ),
                    "ai_references": sum(
                        str(p.get("source")) in {str(source["id"]), source["name"]}
                        and is_protected(p.get("path", ""), is_dir=False, rules=[rule])
                        for e in events
                        for p in e.get("detail", {}).get("paths", [])
                    ),
                    "policy_self_test": is_protected(
                        sample, is_dir=False, rules=[rule]
                    ),
                    "synced": bool(source.get("last_commit")),
                }
            )
    return {
        "rules": reports,
        "valid": all(
            r["stored_files"] == 0
            and r["stored_chunks"] == 0
            and r["historical_accesses"] == 0
            and r["wiki_references"] == 0
            and r["ai_references"] == 0
            and r["policy_self_test"]
            and r["synced"]
            for r in reports
        ),
        "os_evidence_required": True,
    }
