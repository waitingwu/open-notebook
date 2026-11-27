"""Run an isolated, daemon-supervised local preview of CaBook.

Uses one port block and persistent development data, without touching the
database of another CaBook process. All children stay in the supervisor group.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    os.chdir(root)
    load_dotenv(root / ".env", override=False)
    base = int(os.environ.get("MULTICA_PORT", "8502"))
    env = os.environ.copy()
    node_candidates = (
        [Path(os.environ["NODE_BINARY"])] if os.environ.get("NODE_BINARY") else []
    )
    if shutil.which("node"):
        node_candidates.append(Path(shutil.which("node") or "node"))
    node_candidates.extend(
        sorted((Path.home() / ".nvm/versions/node").glob("v*/bin/node"), reverse=True)
    )
    node = None
    for candidate in node_candidates:
        version = (
            subprocess.check_output([str(candidate), "--version"], text=True)
            .strip()
            .lstrip("v")
            .split(".")
        )
        major, minor = int(version[0]), int(version[1])
        if major > 22 or (major == 22 and minor >= 12):
            node = candidate
            break
    if node is None:
        raise RuntimeError("Node.js 22 or newer is required (or set NODE_BINARY)")
    env["PATH"] = (
        str(node.parent)
        + os.pathsep
        + str(root / ".venv/bin")
        + os.pathsep
        + env.get("PATH", "")
    )
    env.update(
        {
            "SURREAL_URL": f"ws://127.0.0.1:{base + 2}/rpc",
            "SURREAL_USER": "root",
            "SURREAL_PASSWORD": "root",
            "SURREAL_PASS": "root",
            "SURREAL_NAMESPACE": "open_notebook",
            "SURREAL_DATABASE": "open_notebook",
            "API_HOST": "127.0.0.1",
            "API_PORT": str(base + 1),
            "API_RELOAD": "false",
            "INTERNAL_API_URL": f"http://127.0.0.1:{base + 1}",
            "NEXT_PUBLIC_API_URL": f"http://127.0.0.1:{base + 1}",
            "NEXT_DIST_DIR": ".next-repo-kb-preview",
            "OPEN_NOTEBOOK_DATA_FOLDER": str(root / "data/repo-kb-preview/files"),
        }
    )
    state = root / "data/repo-kb-preview"
    state.mkdir(parents=True, exist_ok=True)
    children: list[subprocess.Popen] = []

    def stop(_signal: int, _frame: object) -> None:
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    def start(args: list[str], cwd: Path = root) -> subprocess.Popen:
        child = subprocess.Popen(args, cwd=cwd, env=env)
        children.append(child)
        return child

    def ready(url: str, child: subprocess.Popen) -> None:
        for _ in range(180):
            if child.poll() is not None:
                raise RuntimeError("A preview service exited during startup")
            try:
                with urllib.request.urlopen(url, timeout=1) as response:
                    if response.status < 500:
                        return
            except (urllib.error.URLError, TimeoutError):
                pass
            time.sleep(1)
        raise RuntimeError("Preview startup timed out")

    try:
        db = start(
            [
                "surreal",
                "start",
                "--bind",
                f"127.0.0.1:{base + 2}",
                "--user",
                "root",
                "--pass",
                "root",
                "--log",
                "warn",
                f"rocksdb:{state / 'surreal'}",
            ]
        )
        ready(f"http://127.0.0.1:{base + 2}/health", db)
        api = start([sys.executable, "run_api.py"])
        ready(f"http://127.0.0.1:{base + 1}/health", api)
        start(
            [
                str(root / ".venv/bin/surreal-commands-worker"),
                "--import-modules",
                "commands",
                "--max-tasks",
                "2",
            ]
        )
        start(
            [
                str(node),
                "node_modules/next/dist/bin/next",
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(base),
            ],
            root / "frontend",
        )
        print(f"CaBook preview: http://localhost:{base}/repo-kb", flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError("A preview service exited; stopping the environment")
    except KeyboardInterrupt:
        pass
    finally:
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=8)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
