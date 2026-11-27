"""Measure both local CLIs against the native KB using only masked DB content.

Questions are read from Markdown Q1..Q10 headings, never from its sample answers.
The engineering page labels below require human confirmation before C2 signoff.
"""

import argparse
import asyncio
import json
import math
import os
import re
from pathlib import Path
from statistics import median
from typing import Any

from surrealdb import AsyncSurreal

from open_notebook.ai.local_cli.chat_model import LocalCLIChatModel
from open_notebook.repo_kb.native_db import record
from open_notebook.repo_kb.retrieve import retrieve

EXPECTED = {
    1: ["tables/DTAV0011_AA"],
    2: ["modules/Z1"],
    3: ["systems/AV"],
    4: ["modules/E0"],
    5: ["sop/index"],
    6: ["modules/O0", "discrepancies"],
    7: ["modules/A0"],
    8: ["modules/Q0"],
    9: ["tables/DTAVO002"],
    10: ["modules/Y0"],
}


def percentile(values: list[float], ratio: float) -> float | None:
    return (
        sorted(values)[max(0, math.ceil(len(values) * ratio) - 1)] if values else None
    )


async def main(args: argparse.Namespace) -> None:
    questions = [
        (int(n), q.strip())
        for n, q in re.findall(r"^## Q(\d+)\. (.+)$", args.questions.read_text(), re.M)
    ]
    if len(questions) != 10:
        raise ValueError("Exactly ten numbered question headings are required")
    output = {
        "label_status": "engineering draft; requires human confirmation",
        "rounds": args.rounds,
        "results": [],
        "summaries": {},
    }
    db: Any
    async with AsyncSurreal(args.url) as db:
        await db.signin(
            {
                "username": os.environ.get("SURREAL_USER", "root"),
                "password": os.environ.get("SURREAL_PASSWORD", "root"),
            }
        )
        await db.use(
            os.environ.get("SURREAL_NAMESPACE", "open_notebook"),
            os.environ.get("SURREAL_DATABASE", "open_notebook"),
        )
        kb = record(args.kb, "repo_kb")
        for provider in args.providers:
            for turn in range(args.rounds):
                for number, question in questions:
                    result = await retrieve(
                        db,
                        kb,
                        question,
                        model=LocalCLIChatModel(
                            provider=provider, model_name="default"
                        ),
                    )
                    metrics = result["metrics"]
                    found = set(
                        metrics["entities"] + metrics["selected"] + metrics["bm25"]
                    )
                    needed = EXPECTED[number]
                    row = {
                        "provider": provider,
                        "round": turn + 1,
                        "question_number": number,
                        "question": question,
                        "necessary_pages": needed,
                        "necessary_hits": sorted(found.intersection(needed)),
                        "keyword_hits": sorted(
                            set(metrics["bm25"]).intersection(needed)
                        ),
                        **metrics,
                    }
                    output["results"].append(row)
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text(
                        json.dumps(output, ensure_ascii=False, indent=2)
                    )
                    print(
                        json.dumps(
                            {
                                k: row[k]
                                for k in (
                                    "provider",
                                    "round",
                                    "question_number",
                                    "seconds",
                                    "fallback",
                                    "necessary_hits",
                                )
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
            rows = [r for r in output["results"] if r["provider"] == provider]
            latencies = [r["seconds"] for r in rows]
            selection = [
                r["selection"]["seconds"] for r in rows if "seconds" in r["selection"]
            ]
            denominator = sum(len(r["necessary_pages"]) for r in rows)
            output["summaries"][provider] = {
                "retrieval_p50": median(latencies),
                "retrieval_p95": percentile(latencies, 0.95),
                "selection_p50": median(selection) if selection else None,
                "selection_p95": percentile(selection, 0.95),
                "fallbacks": sum(bool(r["fallback"]) for r in rows),
                "necessary_page_recall": sum(len(r["necessary_hits"]) for r in rows)
                / denominator,
                "keyword_only_recall": sum(len(r["keyword_hits"]) for r in rows)
                / denominator,
            }
            args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(json.dumps(output["summaries"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", default=os.environ.get("SURREAL_URL", "ws://127.0.0.1:41002/rpc")
    )
    parser.add_argument("--kb", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["claude_code", "codex_cli"],
        default=["claude_code", "codex_cli"],
    )
    parser.add_argument(
        "--output", type=Path, default=Path("output/retrieval-benchmark.json")
    )
    asyncio.run(main(parser.parse_args()))
