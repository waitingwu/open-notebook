"""Maintenance CLI using the same SurrealDB services as the web application."""

from __future__ import annotations

import argparse
import asyncio
import json


async def _run(args: argparse.Namespace) -> object:
    from open_notebook.database.repository import db_connection, parse_record_ids
    from open_notebook.repo_kb.native_db import config_hash, one, query, record
    from open_notebook.repo_kb.native_jobs import execute_job, submit_job

    async with db_connection() as db:
        if args.command == "list":
            return parse_record_ids(await query(db, "SELECT * FROM repo_kb;"))
        kb = record(args.kb, "repo_kb")
        await one(db, kb, "repo_kb")
        if args.command == "search":
            from open_notebook.repo_kb.native_lookup import search

            return await search(db, kb, args.query, category=args.category)
        if args.command == "verify":
            from open_notebook.repo_kb.native_verify import verify_exclusions

            return await verify_exclusions(db, kb)
        if args.command == "review-source":
            source = await one(db, args.source, "repo_source")
            if source["kb"] != kb:
                raise ValueError("Source belongs to another knowledge base")
            return {
                "source": str(source["id"]),
                "protected": source["protected"],
                "config_hash": config_hash(source),
                "notice": "Pass this hash with --confirm-protection for first sync, after reviewing every rule.",
            }
        kind = args.command.replace("-", "_")
        options = {}
        source_id = None
        if args.command == "sync":
            source_id = record(args.source, "repo_source")
            options = {
                "mode": args.mode,
                "confirmed": bool(args.confirm_protection),
                "config_hash": args.confirm_protection,
            }
        elif args.command in {"compile-rules", "compile-flows"}:
            options = {
                "modules" if args.command == "compile-rules" else "flows": args.items,
                "model_id": args.model,
            }
        job = await submit_job(
            db,
            kb,
            kind,
            source_id=source_id,
            options=options,
            enqueue=not args.foreground,
        )
        if args.foreground:
            return await execute_job(db, record(job["job_id"], "repo_kb_job"))
        return job


def main(argv: list[str] | None = None) -> None:
    from dotenv import load_dotenv

    load_dotenv(override=False)
    parser = argparse.ArgumentParser(prog="repo_kb", description=__doc__)
    parser.add_argument("--kb", help="Native repo_kb record ID (except list)")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run synchronously, otherwise queue on the existing worker",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    for name in ("build", "verify", "export"):
        sub.add_parser(name)
    review = sub.add_parser("review-source")
    review.add_argument("source")
    sync = sub.add_parser("sync")
    sync.add_argument("source")
    sync.add_argument("--mode", choices=["auto", "full"], default="auto")
    sync.add_argument(
        "--confirm-protection", help="Current configuration hash from review-source"
    )
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--category")
    for name in ("compile-rules", "compile-flows"):
        command = sub.add_parser(name)
        command.add_argument("items", nargs="+")
        command.add_argument("--model")
    args = parser.parse_args(argv)
    if args.command != "list" and not args.kb:
        parser.error("--kb is required")
    try:
        print(
            json.dumps(
                asyncio.run(_run(args)), ensure_ascii=False, indent=2, default=str
            )
        )
    except Exception as exc:
        parser.exit(1, f"Knowledge base command failed: {type(exc).__name__}\n")
