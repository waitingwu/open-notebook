"""Validate citations 〔repo:path#Lx[-Ly]@commit〕 against the mirror and git."""

from __future__ import annotations

import os
import re
import subprocess
from collections import Counter
from typing import Any, Dict, List, Optional

from open_notebook.repo_kb.policy import has_denied_component
from open_notebook.repo_kb.store import Store

CITE_RE = re.compile(
    r"〔([\w.-]+):([^#〕]+)#L(\d+)(?:-L(\d+))?@([0-9a-fA-F]{4,40}|HEAD)〕"
)


def check(
    store: Store, repo: str, path: str, start: int, end: Optional[int], commit: str
) -> str:
    if has_denied_component(path):
        return "denied_path"
    row = store.db.execute(
        "SELECT * FROM file WHERE repo=? AND path=?", (repo, path)
    ).fetchone()
    if row is None:
        return "unknown_file"
    if not row["mirror"]:
        return "no_text"
    with open(store.abs(row["mirror"]), encoding="utf-8") as f:
        n = f.read().count("\n") + 1
    if not (1 <= start <= n) or (end is not None and not (start <= end <= n)):
        return "line_out_of_range"
    repo_path = store.db.execute(
        "SELECT path FROM repo WHERE name=?", (repo,)
    ).fetchone()
    if commit != "HEAD" and repo_path:
        res = subprocess.run(
            [
                "git",
                "-C",
                repo_path[0],
                "rev-parse",
                "--verify",
                "-q",
                f"{commit}^{{commit}}:{path}",
            ],
            capture_output=True,
            text=True,
        )
        if res.returncode != 0:
            return "not_at_commit"
        if res.stdout.strip() != row["blob"]:
            return "content_differs_at_commit"
    return "ok"


def validate_text(store: Store, text: str) -> Dict[str, Any]:
    results: Counter = Counter()
    bad: List[Dict[str, str]] = []
    for m in CITE_RE.finditer(text):
        repo, path, s, e, commit = (
            m.group(1),
            m.group(2),
            int(m.group(3)),
            m.group(4),
            m.group(5),
        )
        r = check(store, repo, path, s, int(e) if e else None, commit)
        results[r] += 1
        if r != "ok" and len(bad) < 30:
            bad.append({"cite": m.group(0), "result": r})
    return {"total": sum(results.values()), "by_result": dict(results), "bad": bad}


def validate_wiki(store: Store, sub: str = "") -> Dict[str, Any]:
    root = store.abs(os.path.join("wiki", sub))
    out: Dict[str, Any] = {}
    agg: Counter = Counter()
    seen_cache: Dict[str, str] = {}
    for dp, _, fns in os.walk(root):
        for fn in fns:
            if not fn.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(dp, fn), store.abs("wiki"))
            with open(os.path.join(dp, fn), encoding="utf-8") as f:
                text = f.read()
            # de-duplicate identical citations for speed
            uniq = set(CITE_RE.findall(text))
            res: Counter = Counter()
            for repo, path, s, e, commit in uniq:
                key = f"{repo}|{path}|{s}|{e}|{commit}"
                if key not in seen_cache:
                    seen_cache[key] = check(
                        store, repo, path, int(s), int(e) if e else None, commit
                    )
                res[seen_cache[key]] += 1
            agg.update(res)
            if sub or any(k != "ok" for k in res):
                out[rel] = dict(res)
    return {
        "unique_citations_by_result": dict(agg),
        "pages_with_problems_or_detail": out,
    }
