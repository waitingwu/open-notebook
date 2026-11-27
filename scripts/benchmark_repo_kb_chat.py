"""Record ten explicit acceptance questions through the ordinary chat API.

The report intentionally contains the requested Q&A evidence. Application AI
audit logs continue storing only metadata; no source repo is accessed here.
"""

import argparse
import json
import re
import time
from pathlib import Path

import httpx


def main(args: argparse.Namespace) -> None:
    questions = [
        (int(n), q.strip())
        for n, q in re.findall(r"^## Q(\d+)\. (.+)$", args.questions.read_text(), re.M)
    ]
    report = {
        "notebook": args.notebook,
        "kb": args.kb,
        "model": args.model,
        "results": [],
    }
    with httpx.Client(base_url=args.api.rstrip("/"), timeout=650) as client:
        mounts = client.get(f"/repo-kb/notebooks/{args.notebook}/mounts")
        mounts.raise_for_status()
        if not any(k["id"] == args.kb for k in mounts.json()):
            raise ValueError(
                "Mount the KB explicitly in the notebook before running this benchmark"
            )
        for number, question in questions:
            if args.only and number not in args.only:
                continue
            session = client.post(
                "/chat/sessions",
                json={
                    "notebook_id": args.notebook,
                    "title": f"CATH-10 Q{number}",
                    "model_override": args.model,
                },
            )
            session.raise_for_status()
            session_id = session.json()["id"]
            started = time.monotonic()
            result = client.post(
                "/chat/execute",
                json={
                    "session_id": session_id,
                    "message": question,
                    "context": {"sources": [], "notes": []},
                    "model_override": args.model,
                },
            )
            row = {
                "number": number,
                "question": question,
                "session_id": session_id,
                "http_status": result.status_code,
                "seconds": round(time.monotonic() - started, 3),
            }
            if result.status_code == 200:
                answer = result.json()["messages"][-1]
                row.update(
                    {
                        "message_id": answer["id"],
                        "answer": answer["content"],
                        "citations": answer.get("repo_citations", {}),
                    }
                )
                row["citation_total"] = len(row["citations"])
                row["citation_valid"] = sum(row["citations"].values())
                row["citation_rate"] = (
                    row["citation_valid"] / row["citation_total"]
                    if row["citation_total"]
                    else 0
                )
            else:
                row["error"] = result.text[:1000]
            report["results"].append(row)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            print(
                json.dumps(
                    {
                        k: v
                        for k, v in row.items()
                        if k not in {"answer", "citations", "question"}
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:41001/api")
    parser.add_argument("--notebook", required=True)
    parser.add_argument("--kb", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--only", nargs="*", type=int)
    parser.add_argument(
        "--output", type=Path, default=Path("output/chat-benchmark.json")
    )
    main(parser.parse_args())
