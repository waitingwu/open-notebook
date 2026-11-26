"""First import and git-diff based incremental update."""

from __future__ import annotations

import os
import shutil
import tempfile
from collections import Counter
from typing import Any, Dict, List

from open_notebook.repo_kb.classify import classify, module_of
from open_notebook.repo_kb.config import RepoConfig
from open_notebook.repo_kb.extract import ext_of, extract
from open_notebook.repo_kb.gitsource import GitRepo
from open_notebook.repo_kb.mask import CODE_EXTS, mask_text
from open_notebook.repo_kb.policy import has_denied_component
from open_notebook.repo_kb.store import Store


def _process(
    store: Store, cfg: RepoConfig, path: str, blob: str, data: bytes, tmp: str
) -> Dict[str, Any]:
    assert not has_denied_component(path), path  # defence in depth
    store.log_access(cfg.name, path, blob)
    text, method = extract(path, data, tmp)
    masks: Dict[str, int] = {}
    if text is not None:
        text, masks = mask_text(text, is_code=ext_of(path) in CODE_EXTS)
    category = classify(cfg.role, path, text)
    row = {
        "repo": cfg.name,
        "path": path,
        "blob": blob,
        "category": category,
        "module": module_of(path),
        "method": method,
        "last_commit": None,
        "last_date": None,
        "lines": text.count("\n") + 1 if text is not None else 0,
        "masks": masks,
        "mirror": store.mirror_rel(cfg.name, path, method != "text")
        if text is not None
        else None,
    }
    store.put_file(row, text)
    return row


def _verified_last_commits(
    git: GitRepo, commit: str, rows: Dict[str, str]
) -> Dict[str, Any]:
    """Last-change commit per path, checked so the blob at that commit is the current blob."""
    bulk = git.last_commits(commit)
    out: Dict[str, Any] = {}
    fixed = 0
    for path, blob in rows.items():
        cand = bulk.get(path)
        if cand and git.blob_at(cand[0], path) == blob:
            out[path] = cand
            continue
        cand = git.last_commit_of(commit, path)
        if git.blob_at(cand[0], path) != blob:
            cand = (commit, cand[1])
        out[path] = cand
        fixed += 1
    return out


def import_repo(store: Store, cfg: RepoConfig, progress=print) -> Dict[str, Any]:
    git = GitRepo(cfg.path)
    tmp = tempfile.mkdtemp(prefix="repo-kb-", dir=store.data_dir)
    try:
        commit = git.head()
        stats: Counter = Counter()
        masks: Counter = Counter()
        mirror_root = store.abs(f"mirror/{cfg.name}")
        if os.path.isdir(mirror_root):
            shutil.rmtree(mirror_root)
        store.db.execute("DELETE FROM file WHERE repo=?", (cfg.name,))
        store.db.execute("DELETE FROM fts WHERE repo=?", (cfg.name,))
        entries = list(git.walk(commit, cfg.rules.allows_dir, cfg.rules.allows_file))
        for n, e in enumerate(entries, 1):
            row = _process(store, cfg, e.path, e.blob, git.read_blob(e.blob), tmp)
            stats[row["category"] + ("" if row["mirror"] else "(未轉文字)")] += 1
            masks.update(row["masks"])
            if n % 250 == 0:
                progress(f"  {cfg.name}: {n}/{len(entries)}")
                store.db.commit()
        store.update_last_commits(
            cfg.name,
            _verified_last_commits(git, commit, {e.path: e.blob for e in entries}),
        )
        store.set_repo(cfg.name, cfg.path, cfg.role, commit)
        detail = {
            "commit": commit,
            "files": len(entries),
            "by_category": dict(stats),
            "masks": dict(masks),
        }
        store.event("import", cfg.name, detail)
        store.db.commit()
        return detail
    finally:
        git.close()
        shutil.rmtree(tmp, ignore_errors=True)


def update_repo(store: Store, cfg: RepoConfig, progress=print) -> Dict[str, Any]:
    old = store.repo_commit(cfg.name)
    if not old:
        return import_repo(store, cfg, progress)
    git = GitRepo(cfg.path)
    tmp = tempfile.mkdtemp(prefix="repo-kb-", dir=store.data_dir)
    try:
        new = git.head()
        if new == old:
            return {"commit": new, "changed": []}
        changed: List[Dict[str, str]] = []
        for status, path in git.diff(old, new):
            if status == "D" or not cfg.rules.allows_file(path):
                if store.db.execute(
                    "SELECT 1 FROM file WHERE repo=? AND path=?", (cfg.name, path)
                ).fetchone():
                    store.delete_file(cfg.name, path)
                    changed.append({"status": "D", "path": path, "category": "-"})
                continue
            blob, data = git.read_path(new, path)
            row = _process(store, cfg, path, blob, data, tmp)
            changed.append(
                {"status": status, "path": path, "category": row["category"]}
            )
        blobs = {r["path"]: r["blob"] for r in store.files(repo=cfg.name)}
        store.update_last_commits(
            cfg.name,
            _verified_last_commits(
                git,
                new,
                {c["path"]: blobs[c["path"]] for c in changed if c["path"] in blobs},
            ),
        )
        store.set_repo(cfg.name, cfg.path, cfg.role, new)
        detail = {"from": old, "commit": new, "changed": changed}
        store.event("update", cfg.name, detail)
        store.db.commit()
        return detail
    finally:
        git.close()
        shutil.rmtree(tmp, ignore_errors=True)
