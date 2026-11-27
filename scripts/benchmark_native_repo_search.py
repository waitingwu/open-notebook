"""Benchmark the native index on a masked CATH-9 SQLite export, read-only.

Run from the project root: python scripts/benchmark_native_repo_search.py PATH.
An isolated temporary SurrealDB holds the benchmark data; no source repo is read.
"""

import argparse
import asyncio
import resource
import secrets
import socket
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from surrealdb import AsyncSurreal, RecordID

from open_notebook.repo_kb.native_search_store import (
    build_generation,
    candidate_targets,
    publish_generation,
)


async def benchmark(
    db_path: Path, port: int, password: str, proc: subprocess.Popen
) -> None:
    endpoint = f"127.0.0.1:{port}"
    for _ in range(100):
        if proc.poll() is not None:
            raise RuntimeError("Isolated SurrealDB failed to start")
        try:
            urllib.request.urlopen(f"http://{endpoint}/health", timeout=1).read()
            break
        except urllib.error.URLError:
            await asyncio.sleep(0.1)
    else:
        raise RuntimeError("Isolated SurrealDB did not become ready")

    def rss_mib() -> float:
        value = subprocess.check_output(
            ["ps", "-o", "rss=", "-p", str(proc.pid)], text=True
        )
        return int(value.strip()) / 1024

    db: Any
    async with AsyncSurreal(f"ws://{endpoint}/rpc") as db:
        await db.signin({"username": "bench", "password": password})
        await db.use("bench", "bench")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(
            Path("open_notebook/database/migrations/30.surrealql").read_text()
        )
        kb = RecordID("repo_kb", "bench")
        source = RecordID("repo_source", "bench")
        snapshot = RecordID("repo_source_snapshot", "bench")
        file = RecordID("repo_file", "bench")
        await db.query("CREATE $id SET name='bench', scope='global';", {"id": kb})
        conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
        cursor = conn.execute(
            "SELECT body FROM fts WHERE lower('/' || path || '/') NOT LIKE '%/usr/%'"
        )
        documents: list[tuple[RecordID, str]] = []
        peak = rss_mib()
        load_started = time.monotonic()
        while batch := cursor.fetchmany(250):
            values = []
            for (body,) in batch:
                target = RecordID("repo_chunk", str(len(documents)))
                body = body or ""
                documents.append((target, body))
                values.append(
                    {
                        "id": target,
                        "file": file,
                        "source": source,
                        "snapshot": snapshot,
                        "path": "masked",
                        "category": "other",
                        "start_line": 1,
                        "end_line": 1,
                        "body": body,
                    }
                )
            await db.query(
                "INSERT INTO repo_chunk $batch RETURN NONE;", {"batch": values}
            )
            peak = max(peak, rss_mib())
        conn.close()
        load_seconds = time.monotonic() - load_started

        samples: list[float] = []
        stop = threading.Event()

        def monitor() -> None:
            while not stop.wait(1):
                sample = rss_mib()
                samples.append(sample)
                if sample >= 2048:
                    proc.terminate()
                    return

        worker = threading.Thread(target=monitor)
        worker.start()
        started = time.monotonic()
        try:
            generation = await build_generation(db.query, kb, documents)
            await publish_generation(db.query, kb, generation)
        finally:
            stop.set()
            worker.join()
        index_seconds = time.monotonic() - started
        peak = max([peak, rss_mib(), *samples])
        # macOS reports ru_maxrss in bytes; Linux reports KiB.
        import sys

        divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
        python_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / divisor
        print(
            f"chunks={len(documents)} load_s={load_seconds:.2f} index_s={index_seconds:.2f} db_peak_rss_mib={peak:.1f} python_peak_rss_mib={python_mib:.1f}"
        )
        for term in ("執行紀錄位置", "DTAV0011_AA", "SQLCODE=-803"):
            started = time.monotonic()
            ids = await candidate_targets(db.query, kb, term)
            rows = await db.query("SELECT body FROM $ids;", {"ids": ids}) if ids else []
            exact = sum(term.casefold() in row["body"].casefold() for row in rows)
            print(
                f"query={term} candidates={len(ids)} exact={exact} seconds={time.monotonic() - started:.3f}"
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    args = parser.parse_args()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    password = secrets.token_urlsafe(24)
    proc = subprocess.Popen(
        [
            "surreal",
            "start",
            "--user",
            "bench",
            "--pass",
            password,
            "--bind",
            f"127.0.0.1:{port}",
            "--log",
            "none",
            "memory",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        asyncio.run(benchmark(args.database, port, password, proc))
    finally:
        proc.terminate()
        proc.wait(timeout=10)


if __name__ == "__main__":
    main()
