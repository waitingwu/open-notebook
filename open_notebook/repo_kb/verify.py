"""Evidence that hard-denied directories (``usr``) were never read, indexed or sent."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict

from open_notebook.repo_kb.config import KBConfig
from open_notebook.repo_kb.policy import has_denied_component, is_denied_dir_name
from open_notebook.repo_kb.store import Store

_USR_PATH = re.compile(r"(?i)(^|/)usr/")


def verify_denied(store: Store, cfg: KBConfig) -> Dict[str, Any]:
    checks: Dict[str, Any] = {}
    # 1. policy self-test on the known location
    checks["policy_blocks_known_path"] = has_denied_component(
        "CSR2/source/AV_SRC/usr/any/File.java"
    )
    # 2. every blob ever read by ingest
    total = bad = 0
    with open(store.abs("access.jsonl"), encoding="utf-8") as f:
        for line in f:
            total += 1
            if has_denied_component(json.loads(line)["path"]):
                bad += 1
    checks["ingest_reads_total"] = total
    checks["ingest_reads_under_usr"] = bad
    # 3. manifest + keyword index
    checks["manifest_paths_under_usr"] = sum(
        1 for r in store.files() if has_denied_component(r["path"])
    )
    checks["fts_rows_under_usr"] = sum(
        1
        for (p,) in store.db.execute("SELECT DISTINCT path FROM fts")
        if has_denied_component(p)
    )
    # 4. mirror + wiki trees (what the agent can see)
    usr_dirs = []
    usr_refs = []
    for sub in ("mirror", "wiki"):
        for dp, dns, fns in os.walk(store.abs(sub)):
            usr_dirs += [
                os.path.join(dp, d)
                for d in dns
                if is_denied_dir_name(d) and "_canary" not in dp
            ]
            if sub == "wiki":
                for fn in fns:
                    with open(os.path.join(dp, fn), encoding="utf-8") as fh:
                        if re.search(r"AV_SRC/usr/", fh.read()):
                            usr_refs.append(
                                os.path.relpath(os.path.join(dp, fn), store.data_dir)
                            )
    checks["mirror_or_wiki_dirs_named_usr"] = usr_dirs
    checks["wiki_pages_citing_usr_paths"] = usr_refs
    # 5. everything sent to a model: rule compilation inputs are spec mirror files,
    #    agent tool calls are recorded per run
    asks = [
        json.loads(d)
        for (d,) in store.db.execute("SELECT detail FROM event WHERE action='ask'")
    ]
    checks["agent_runs"] = len(asks)
    checks["agent_paths_outside_or_usr"] = sum(
        len(a.get("outside_or_denied_paths", [])) for a in asks
    )
    checks["passed"] = (
        checks["policy_blocks_known_path"]
        and bad == 0
        and checks["manifest_paths_under_usr"] == 0
        and checks["fts_rows_under_usr"] == 0
        and not usr_dirs
        and not usr_refs
    )
    store.event("verify_usr", "*", checks)
    store.db.commit()
    return checks
