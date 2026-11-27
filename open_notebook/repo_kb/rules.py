"""LLM-compiled business-rule pages (one per module), via the local Claude Code CLI.

Only masked mirror text of *spec* files is sent; the model runs without tools.
Every statement must carry a citation; :mod:`cite` validates them afterwards.
Audit follows the existing rule: no prompt/answer text, no tokens are logged.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from typing import Any, Dict, List, Optional

from open_notebook.ai.local_cli.runners import run_claude
from open_notebook.repo_kb.classify import SPEC
from open_notebook.repo_kb.store import Store

MAX_CHARS = 150_000

SYSTEM = """你是資深系統分析師，負責把系統規格書整理成「業務規則 wiki 頁」。
規則：
1. 只能根據提供的原文撰寫，不得臆測；原文沒寫的就不要寫。
2. 以「業務流程」為單位分節（例如：受理→掃描→登打→審批→歸檔），每節說明觸發時機、處理步驟、判斷規則、涉及的資料表與程式。
3. 每一個條列或段落結尾都必須附引文，格式嚴格為 〔repo:路徑#L起-L迄@commit〕，路徑與 commit 必須逐字使用來源標頭提供的值，行號必須是原文前綴的 L 行號。
4. 若不同文件互相矛盾，或檔名與內文不符，另立「## 文件間不一致」一節列出並附雙方引文。
5. 原文中的 <IP>、<ACCOUNT>、<SECRET>、<CONN> 是遮蔽標記，照抄即可，不要猜測原值。
6. 使用繁體中文，輸出 Markdown，不要輸出 H1 以外的前言或結語。第一行為「# 業務規則：<模組代號> <模組名稱>」。"""


def _source_block(store: Store, row) -> str:
    with open(store.abs(row["mirror"]), encoding="utf-8") as f:
        lines = f.read().split("\n")
    body = "\n".join(
        f"L{i}: {ln.strip()}" for i, ln in enumerate(lines, 1) if ln.strip()
    )
    return f"=== 來源 repo={row['repo']} 路徑={row['path']} commit={(row['last_commit'] or 'HEAD')[:10]} ===\n{body}\n"


def compile_module(
    store: Store, module: str, model: Optional[str] = None
) -> Dict[str, Any]:
    rows = [
        r for r in store.files(category=SPEC) if r["module"] == module and r["mirror"]
    ]
    if not rows:
        return {"module": module, "status": "no_specs"}
    blocks: List[str] = []
    used = []
    total = 0
    for r in sorted(rows, key=lambda r: r["path"]):
        b = _source_block(store, r)
        if total + len(b) > MAX_CHARS:
            continue
        blocks.append(b)
        used.append(r["path"])
        total += len(b)
    name = rows[0]["path"].split("/AV影像系統/", 1)[-1].split("/", 1)[0]
    prompt = (
        f"模組：{module}（資料夾 {name}）\n以下是該模組的規格原文（每行前綴為原始行號）：\n\n"
        + "\n".join(blocks)
    )
    started = time.monotonic()
    text = ""
    usage: Dict[str, Any] = {}
    for ev in run_claude(SYSTEM, prompt, model=model, timeout=900):
        if ev["kind"] == "done":
            text = ev.get("text") or text
        elif ev["kind"] == "usage":
            usage = ev.get("usage") or ev
    sources = "\n".join(
        f"- {r['repo']}:{p}" for r in rows for p in [r["path"]] if p in used
    )
    page = (
        "---\n"
        f"type: rules\nmodule: {module}\ngenerated_by: claude_code (local CLI)\n"
        f"generated_at: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}\n"
        f"source_blobs: {json.dumps({r['path']: r['blob'] for r in rows if r['path'] in used}, ensure_ascii=False)}\n"
        "---\n" + text.strip() + f"\n\n## 編譯來源\n\n{sources}\n"
    )
    dest = store.abs(f"wiki/rules/{module}.md")
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        f.write(page)
    # audit: metadata only (no prompt / answer text, no tokens)
    detail = {
        "module": module,
        "sources": len(used),
        "skipped_for_size": len(rows) - len(used),
        "prompt_chars": len(prompt),
        "prompt_sha1": hashlib.sha1(prompt.encode()).hexdigest()[:12],
        "answer_chars": len(text),
        "seconds": round(time.monotonic() - started, 1),
        "usage": {k: v for k, v in usage.items() if isinstance(v, (int, float))}
        if isinstance(usage, dict)
        else {},
    }
    store.event("compile_rules", module, detail)
    store.db.commit()
    return detail


def compile_modules(
    store: Store, modules: List[str], model: Optional[str] = None
) -> List[Dict[str, Any]]:
    return [compile_module(store, m, model) for m in modules]


def stale_rule_modules(store: Store) -> List[str]:
    """Modules whose rule page was compiled from spec blobs that have since changed."""
    out: List[str] = []
    wdir = store.abs("wiki/rules")
    if not os.path.isdir(wdir):
        return out
    current = {r["path"]: r["blob"] for r in store.files(category=SPEC)}
    for fn in os.listdir(wdir):
        if not fn.endswith(".md"):
            continue
        with open(os.path.join(wdir, fn), encoding="utf-8") as f:
            head = f.read(20000)
        for line in head.split("\n"):
            if line.startswith("source_blobs: "):
                blobs = json.loads(line[len("source_blobs: ") :])
                module = fn[:-3]
                mod_specs = {p for p, _ in current.items() if f"/{module}_" in p}
                if any(current.get(p) != b for p, b in blobs.items()) or (
                    mod_specs - set(blobs)
                ):
                    out.append(module)
                break
    return out
