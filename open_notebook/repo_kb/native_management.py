"""Knowledge-base scopes, notebook mounts, and cascading deletion."""

from __future__ import annotations

from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import ConflictError, InvalidInputError
from open_notebook.repo_kb.native_db import one, query, record, transaction, visible_kb
from open_notebook.repo_kb.native_lock import acquire, release


async def mounts(db: Any, notebook: RecordID) -> list[dict[str, Any]]:
    row = await one(db, notebook, "notebook")
    result = []
    for target in row.get("repo_kbs", []):
        result.append(await visible_kb(db, target, notebook))
    return result


async def set_mounts(
    db: Any, notebook: RecordID, values: list[str]
) -> list[dict[str, Any]]:
    await one(db, notebook, "notebook")
    ids = [record(value, "repo_kb") for value in dict.fromkeys(values)]
    for kb in ids:
        await visible_kb(db, kb, notebook)
    await query(db, "UPDATE $id SET repo_kbs=$kbs;", {"id": notebook, "kbs": ids})
    return await mounts(db, notebook)


async def update_kb(
    db: Any, kb: RecordID, data: dict[str, Any], detach_confirmed: list[str]
) -> dict[str, Any]:
    lock = await acquire(db.query_raw, kb)
    try:
        current = await one(db, kb, "repo_kb")
        changes = {
            k: v for k, v in data.items() if v is not None and k != "detach_confirmed"
        }
        scope = changes.get("scope", current["scope"])
        owner = changes.get("owner_notebook", current.get("owner_notebook"))
        detach = []
        if scope == "notebook":
            if not owner:
                raise InvalidInputError("Choose an owner notebook")
            owner = record(owner, "notebook")
            await one(db, owner, "notebook")
            changes["owner_notebook"] = owner
            notebooks = (
                await query(
                    db,
                    "SELECT id,name FROM notebook WHERE repo_kbs CONTAINS $kb;",
                    {"kb": kb},
                )
                or []
            )
            detach = [n["id"] for n in notebooks if n["id"] != owner]
            if not {str(n) for n in detach}.issubset(detach_confirmed):
                raise ConflictError(
                    "Confirm detaching these notebooks: "
                    + ", ".join(
                        f"{n['name']} ({n['id']})"
                        for n in notebooks
                        if n["id"] != owner
                    )
                )
        else:
            changes["owner_notebook"] = None
        await transaction(
            db,
            "UPDATE $detach SET repo_kbs=array::complement(repo_kbs, [$kb]); UPDATE $kb MERGE $data; UPDATE $kb SET updated=time::now();",
            {"kb": kb, "data": changes, "detach": detach},
            lock,
        )
    finally:
        await release(db.query_raw, lock)
    return await one(db, kb, "repo_kb")


async def delete_kb(db: Any, kb: RecordID) -> None:
    lock = await acquire(db.query_raw, kb)
    try:
        sources = (
            await query(
                db, "SELECT VALUE id FROM repo_source WHERE kb=$kb;", {"kb": kb}
            )
            or []
        )
        pages = (
            await query(
                db, "SELECT VALUE id FROM repo_wiki_page WHERE kb=$kb;", {"kb": kb}
            )
            or []
        )
        generations = (
            await query(
                db,
                "SELECT VALUE id FROM repo_search_generation WHERE kb=$kb;",
                {"kb": kb},
            )
            or []
        )
        sql = """UPDATE notebook SET repo_kbs=array::complement(repo_kbs, [$kb]) WHERE repo_kbs CONTAINS $kb;
        DELETE repo_chunk WHERE $sources CONTAINS source;
        DELETE repo_file WHERE $sources CONTAINS source;
        DELETE repo_source_snapshot WHERE $sources CONTAINS source;
        DELETE repo_access_log WHERE $sources CONTAINS source;
        DELETE repo_exclusion_audit WHERE $sources CONTAINS source;
        DELETE repo_wiki_revision WHERE $pages CONTAINS page;
        DELETE repo_search_posting WHERE $generations CONTAINS generation;
        DELETE repo_search_document WHERE $generations CONTAINS generation;
        """
        for table in (
            "repo_wiki_note",
            "repo_wiki_section",
            "repo_wiki_page",
            "repo_discrepancy",
            "repo_kb_event",
            "repo_kb_job",
            "repo_wiki_export",
            "repo_search_generation",
            "repo_source",
        ):
            sql += f"DELETE {table} WHERE kb=$kb;\n"
        sql += "DELETE $kb;"
        await transaction(
            db,
            sql,
            {"kb": kb, "sources": sources, "pages": pages, "generations": generations},
            lock,
        )
    finally:
        await release(db.query_raw, lock)
