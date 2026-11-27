"""One-way Markdown export; source repositories are never export targets."""

from __future__ import annotations

import asyncio
import io
import json
import os
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from surrealdb import RecordID

from open_notebook.exceptions import ConfigurationError
from open_notebook.repo_kb.native_access import check_policy_version
from open_notebook.repo_kb.native_content import page as read_page
from open_notebook.repo_kb.native_db import one, query, transaction
from open_notebook.repo_kb.native_lock import WriteLock
from open_notebook.repo_kb.native_paths import validate_source_path
from open_notebook.repo_kb.native_settings import allowed_roots, data_roots


async def validate_config(db: Any, path: str, branch: str, subdir: str) -> str:
    root = await asyncio.to_thread(
        validate_source_path,
        path,
        allowed_roots=await allowed_roots(db),
        data_roots=data_roots(),
    )
    sources = await query(db, "SELECT path FROM repo_source;") or []
    for source in sources:
        other = Path(source["path"]).resolve()
        if root == other or other in root.parents or root in other.parents:
            raise ConfigurationError(
                "The export repository must be separate from every source repository"
            )
    if (
        not branch
        or branch.startswith("-")
        or subprocess.run(
            ["git", "check-ref-format", "--branch", branch], capture_output=True
        ).returncode
    ):
        raise ConfigurationError("Invalid export branch")
    parts = PurePosixPath(subdir)
    if (
        parts.is_absolute()
        or subdir in {".", ".."}
        or any(p.casefold() in {"..", ".git"} for p in parts.parts)
        or not subdir.strip("/")
        or "\\" in subdir
    ):
        raise ConfigurationError(
            "Export subfolder must be a relative folder outside .git"
        )
    return str(root)


async def documents(db: Any, kb: RecordID) -> dict[str, bytes]:
    base = await one(db, kb, "repo_kb")
    rows = (
        await query(db, "SELECT slug FROM repo_wiki_page WHERE kb=$kb;", {"kb": kb})
        or []
    )
    values = {}
    folder = (
        re.sub(r"[^\w\u3400-\u9fff.-]+", "-", base["name"]).strip(".-")
        or "knowledge-base"
    )
    for row in rows:
        page = await read_page(db, kb, row["slug"])
        metadata = {
            k: page.get(k)
            for k in (
                "title",
                "kind",
                "summary",
                "revision",
                "model",
                "generated_by",
                "source_commits",
                "stale",
            )
        }
        body = (
            "---\n"
            + json.dumps(metadata, ensure_ascii=False, indent=2)
            + "\n---\n\n"
            + page["body"]
        )
        for note in page["notes"]:
            body += (
                "\n\n## 人工補充"
                + ("（需重新確認）" if note["stale"] else "")
                + "\n\n"
                + note["body"]
            )
        values[f"{folder}/{page['slug']}.md"] = body.encode("utf-8")
    await check_policy_version(db, kb, base.get("policy_version", 0))
    return values


async def export_zip(db: Any, kb: RecordID) -> bytes:
    values = await documents(db, kb)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, body in values.items():
            archive.writestr(name, body)
    return buffer.getvalue()


def _commit(
    path: str, branch: str, subdir: str, values: dict[str, bytes], message: str
) -> str:
    def git(
        *args: str,
        body: bytes | None = None,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", "-C", path, *args],
            input=body,
            capture_output=True,
            check=check,
            env=env,
        )

    reference = "refs/heads/" + branch
    previous = git("rev-parse", "--verify", reference, check=False)
    old = previous.stdout.decode().strip() if previous.returncode == 0 else None
    # Private index and plumbing avoid checkout/reset and preserve a user's
    # working tree, staging area, branch, and unrelated export-repo files.
    with tempfile.TemporaryDirectory(prefix="repo-kb-export-") as folder:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(folder) / "index")}
        git("read-tree", old or "--empty", env=env)
        prefix = subdir.strip("/") + "/"
        if old:
            entries = git(
                "ls-tree", "-r", "--name-only", "-z", old, "--", prefix
            ).stdout.split(b"\0")
            if any(entries):
                git(
                    "update-index",
                    "--force-remove",
                    "-z",
                    "--stdin",
                    body=b"\0".join(e for e in entries if e) + b"\0",
                    env=env,
                )
        for name, body in values.items():
            blob = (
                git("hash-object", "-w", "--stdin", body=body).stdout.decode().strip()
            )
            git(
                "update-index",
                "--add",
                "--cacheinfo",
                f"100644,{blob},{prefix}{name}",
                env=env,
            )
        tree = git("write-tree", env=env).stdout.decode().strip()
        args = ["commit-tree", tree] + (["-p", old] if old else [])
        commit = git(*args, body=message.encode(), env=env).stdout.decode().strip()
        git("update-ref", reference, commit, old or "0" * 40)
        return commit


async def export_git(db: Any, kb: RecordID, lock: WriteLock) -> dict[str, Any]:
    rows = (
        await query(db, "SELECT * FROM repo_wiki_export WHERE kb=$kb;", {"kb": kb})
        or []
    )
    if not rows or not rows[0]["enabled"]:
        return {"skipped": True}
    config = rows[0]
    root = await validate_config(
        db, config["repo_path"], config["branch"], config["subdir"]
    )
    values = await documents(db, kb)
    base = await one(db, kb, "repo_kb")
    message = f"CaBook wiki export: {base['name']}\n\nSources: {base.get('last_build_commit_set', {})}\nGenerated from SurrealDB wiki pages; no push.\n"
    commit = await asyncio.to_thread(
        _commit, root, config["branch"], config["subdir"], values, message
    )
    await transaction(
        db,
        "UPDATE $id SET last_export_commit=$commit,last_export_at=time::now(),last_error=NONE;",
        {"id": config["id"], "commit": commit},
        lock,
    )
    return {"commit": commit, "files": len(values), "branch": config["branch"]}
