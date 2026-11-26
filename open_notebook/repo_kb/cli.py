"""Command line entry: ``python -m open_notebook.repo_kb <command>``."""

from __future__ import annotations

import argparse
import json
import os
import sys

from open_notebook.repo_kb.config import load_config
from open_notebook.repo_kb.store import Store


def _print(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="repo_kb")
    ap.add_argument(
        "--config", default=os.environ.get("REPO_KB_CONFIG", "repo_kb.yaml")
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="first (full) import")
    p.add_argument("repos", nargs="*")
    p = sub.add_parser("update", help="incremental update via git diff")
    p.add_argument("repos", nargs="*")
    p = sub.add_parser(
        "build", help="generate deterministic wiki pages + spec/code comparison"
    )
    p = sub.add_parser(
        "compile-rules", help="LLM-compile business-rule pages for modules"
    )
    p.add_argument("modules", nargs="+")
    p.add_argument("--model", default=None)
    p = sub.add_parser("validate", help="check every citation in the wiki resolves")
    p = sub.add_parser("search", help="keyword search (trigram) over the mirror")
    p.add_argument("query")
    p.add_argument("--category", action="append", default=[])
    p = sub.add_parser(
        "ask", help="ask the local agent (reads wiki, then repo evidence)"
    )
    p.add_argument("question")
    p.add_argument("--model", default=None)
    p.add_argument("--out", default=None)
    p = sub.add_parser(
        "publish", help="sync wiki pages into a CaBook notebook (REST API)"
    )
    p.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:5055"))
    p.add_argument("--notebook", default="AV 影像系統維運知識庫")
    p.add_argument(
        "--page", action="append", default=None, help="glob under wiki/ (repeatable)"
    )
    p.add_argument(
        "--table", action="append", default=[], help="also publish tables/<NAME>.md"
    )
    p = sub.add_parser(
        "verify-usr", help="prove denied directories were never read/indexed/sent"
    )
    args = ap.parse_args(argv)

    cfg = load_config(args.config)
    store = Store(cfg.data_dir)
    try:
        if args.cmd in ("import", "update"):
            from open_notebook.repo_kb.ingest import import_repo, update_repo

            fn = import_repo if args.cmd == "import" else update_repo
            for r in cfg.repos:
                if args.repos and r.name not in args.repos:
                    continue
                print(f"[{args.cmd}] {r.name} ← {r.path}", file=sys.stderr)
                _print(
                    {r.name: fn(store, r, progress=lambda m: print(m, file=sys.stderr))}
                )
        elif args.cmd == "build":
            from open_notebook.repo_kb.wiki import build_wiki

            _print(build_wiki(store, cfg))
        elif args.cmd == "compile-rules":
            from open_notebook.repo_kb.rules import compile_modules

            _print(compile_modules(store, args.modules, model=args.model))
        elif args.cmd == "validate":
            from open_notebook.repo_kb.cite import validate_wiki

            _print(validate_wiki(store))
        elif args.cmd == "search":
            for row in store.search(args.query, categories=args.category):
                print(
                    f"{row['repo']}:{row['path']}#L{row['start_line']}-L{row['end_line']} [{row['category']}]"
                )
                print("   " + row["snip"].replace("\n", " ⏎ "))
        elif args.cmd == "ask":
            from open_notebook.repo_kb.agent import ask

            _print(ask(store, args.question, model=args.model, out=args.out))
        elif args.cmd == "publish":
            from open_notebook.repo_kb.publish import publish

            _print(
                publish(
                    store,
                    args.api,
                    args.notebook,
                    patterns=args.page,
                    tables=args.table,
                    password=os.environ.get("OPEN_NOTEBOOK_PASSWORD"),
                )
            )
        elif args.cmd == "verify-usr":
            from open_notebook.repo_kb.verify import verify_denied

            _print(verify_denied(store, cfg))
    finally:
        store.close()
