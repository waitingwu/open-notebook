"""Policy changes and deletion under the same fencing lock as source jobs."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import ConflictError, InvalidInputError
from open_notebook.repo_kb.cite import CITE_RE
from open_notebook.repo_kb.native_db import one, query, transaction
from open_notebook.repo_kb.native_lock import acquire, release
from open_notebook.repo_kb.protected_rules import ProtectedRule, is_protected


def parse_rules(values: list[dict[str, Any]]) -> list[ProtectedRule]:
    if len(values) > 100:
        raise InvalidInputError("At most 100 protected rules are allowed")
    try:
        rules = [ProtectedRule(**value) for value in values]
        if any(len(rule.pattern) > 512 for rule in rules):
            raise ValueError("Rule pattern is too long")
        if len({(r.kind, r.pattern.casefold()) for r in rules}) != len(rules):
            raise ValueError("Duplicate protected rules")
        return rules
    except (ValueError, TypeError) as exc:
        raise InvalidInputError(str(exc)) from exc


def _references(
    row: dict[str, Any],
    source: dict[str, Any],
    rules: list[ProtectedRule],
    *,
    coarse: bool = False,
) -> bool:
    for dep in row.get("dependencies", []):
        if str(dep.get("source")) in {
            str(source["id"]),
            source["name"],
        } and (
            (not dep.get("path") and coarse)
            or (
                dep.get("path") and is_protected(dep["path"], is_dir=False, rules=rules)
            )
        ):
            return True
    texts = [row.get(key) or "" for key in ("body", "spec_cite", "code_cite")]
    for text in texts:
        for match in CITE_RE.finditer(text):
            if match.group(1) == source["name"] and is_protected(
                match.group(2), is_dir=False, rules=rules
            ):
                return True
    return False


async def update_protected(
    db: Any,
    source_id: RecordID,
    values: list[dict[str, Any]],
    *,
    confirmations: list[str],
    reason: str,
) -> dict[str, int]:
    rules = parse_rules(values)
    source = await one(db, source_id, "repo_source")
    lock = await acquire(db.query_raw, source["kb"])
    try:
        source = await one(db, source_id, "repo_source")
        old = parse_rules(source.get("protected", []))
        active = {(r.kind, r.pattern.casefold()) for r in rules if r.enabled}
        removed = [
            r.pattern
            for r in old
            if r.enabled and (r.kind, r.pattern.casefold()) not in active
        ]
        if removed and (not reason.strip() or not set(removed).issubset(confirmations)):
            raise ConflictError(
                "Removing or disabling protection requires the exact rule text and a reason"
            )
        files = (
            await query(
                db,
                "SELECT id, path FROM repo_file WHERE source=$source;",
                {"source": source_id},
            )
            or []
        )
        denied = [
            r["id"] for r in files if is_protected(r["path"], is_dir=False, rules=rules)
        ]
        pages = (
            await query(
                db, "SELECT * FROM repo_wiki_page WHERE kb=$kb;", {"kb": source["kb"]}
            )
            or []
        )
        affected = [
            p["id"]
            for p in pages
            if _references(p, source, rules, coarse=bool(denied))
            or (denied and (p["generated_by"] == "build" or not p.get("dependencies")))
        ]
        revisions = (
            await query(
                db,
                "SELECT * FROM repo_wiki_revision WHERE $pages CONTAINS page;",
                {"pages": [p["id"] for p in pages]},
            )
            or []
        )
        bad_revisions = [
            r["id"]
            for r in revisions
            if r["page"] in affected or _references(r, source, rules)
        ]
        notes = (
            await query(
                db, "SELECT * FROM repo_wiki_note WHERE kb=$kb;", {"kb": source["kb"]}
            )
            or []
        )
        bad_notes = [
            n["id"]
            for n in notes
            if n["page"] in affected or _references(n, source, rules)
        ]
        generations = (
            await query(
                db,
                "SELECT id FROM repo_search_generation WHERE kb=$kb;",
                {"kb": source["kb"]},
            )
            or []
        )
        data = [asdict(rule) for rule in rules]
        # Index terms can reveal excluded fragments, so remove old generations,
        # not just their active pointer. Include inactive source snapshots too.
        await transaction(
            db,
            """
            UPDATE $kb SET stale=true, policy_version=policy_version+1;
            UPDATE $kb UNSET search_generation;
            DELETE repo_search_posting WHERE $generations CONTAINS generation;
            DELETE repo_search_document WHERE $generations CONTAINS generation;
            DELETE $generations;
            DELETE repo_chunk WHERE $files CONTAINS file;
            DELETE $files;
            UPDATE $pages SET title='待重建',body='', summary='', citations=[], dependencies=[], stale=true;
            UPDATE repo_discrepancy SET summary='',spec_cite=NONE,code_cite=NONE,note=NONE WHERE kb=$kb;
            DELETE repo_wiki_section WHERE $pages CONTAINS page;
            DELETE $revisions;
            DELETE $notes;
            UPDATE $source SET protected=$rules, needs_full=true;
            CREATE repo_exclusion_audit CONTENT $audit;
        """,
            {
                "kb": source["kb"],
                "source": source_id,
                "rules": data,
                "files": denied,
                "pages": affected,
                "revisions": bad_revisions,
                "notes": bad_notes,
                "generations": [r["id"] for r in generations],
                "audit": {
                    "source": source_id,
                    "action": "edit",
                    "before": {"rules": source.get("protected", [])},
                    "after": {"rules": data},
                    "reason": reason.strip() or None,
                },
            },
            lock,
        )
        return {
            "files_purged": len(denied),
            "pages_invalidated": len(affected),
            "revisions_purged": len(bad_revisions),
            "notes_purged": len(bad_notes),
        }
    finally:
        await release(db.query_raw, lock)


async def delete_source(db: Any, source_id: RecordID) -> None:
    source = await one(db, source_id, "repo_source")
    lock = await acquire(db.query_raw, source["kb"])
    try:
        pages = (
            await query(
                db, "SELECT * FROM repo_wiki_page WHERE kb=$kb;", {"kb": source["kb"]}
            )
            or []
        )
        affected = [
            p["id"]
            for p in pages
            if not p.get("dependencies")
            or any(str(d.get("source")) == str(source_id) for d in p["dependencies"])
        ]
        generations = (
            await query(
                db,
                "SELECT id FROM repo_search_generation WHERE kb=$kb;",
                {"kb": source["kb"]},
            )
            or []
        )
        await transaction(
            db,
            """
            UPDATE $kb SET stale=true, policy_version=policy_version+1;
            UPDATE $kb UNSET search_generation;
            DELETE repo_chunk WHERE source=$source;
            DELETE repo_file WHERE source=$source;
            DELETE repo_source_snapshot WHERE source=$source;
            DELETE repo_search_document WHERE $generations CONTAINS generation;
            DELETE repo_search_posting WHERE $generations CONTAINS generation;
            DELETE $generations;
            UPDATE $pages SET title='待重建',body='',summary='',citations=[],dependencies=[],stale=true;
            UPDATE repo_discrepancy SET summary='',spec_cite=NONE,code_cite=NONE,note=NONE WHERE kb=$kb;
            DELETE repo_wiki_section WHERE $pages CONTAINS page;
            DELETE repo_wiki_revision WHERE $pages CONTAINS page;
            DELETE repo_wiki_note WHERE $pages CONTAINS page;
            DELETE $source;
        """,
            {
                "kb": source["kb"],
                "source": source_id,
                "pages": affected,
                "generations": [g["id"] for g in generations],
            },
            lock,
        )
    finally:
        await release(db.query_raw, lock)
