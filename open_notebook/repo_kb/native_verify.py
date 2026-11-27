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
                    "policy_self_test": is_protected(
                        sample, is_dir=False, rules=[rule]
                    ),
                    "synced": bool(source.get("last_commit")),
                }
            )
    return {
        "rules": reports,
        "valid": all(
            r["stored_files"] == 0 and r["stored_chunks"] == 0 and r["policy_self_test"]
            for r in reports
        ),
        "os_evidence_required": True,
    }
