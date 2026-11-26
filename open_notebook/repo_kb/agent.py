"""Q&A: a local Claude Code agent reads the wiki first, then masked repo evidence.

Sandbox:
- working directory = KB data dir (wiki/ + masked mirror/); the agent has
  only Read / Grep / Glob, in ``dontAsk`` mode, so anything not pre-approved
  (other tools, paths outside the data dir) is denied without prompting;
- explicit deny rules for the source repositories and any ``usr`` directory;
- no MCP servers, no user/global settings or hooks, no session persistence.

Every tool call's path argument is captured from the stream and checked; the
audit event stores paths and counts only (no question/answer text, no tokens).
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from typing import Any, Dict, List, Optional

from open_notebook.ai.local_cli.process import resolve_executable
from open_notebook.ai.local_cli.runners import _next_line, _Proc
from open_notebook.repo_kb.cite import validate_text
from open_notebook.repo_kb.policy import has_denied_component
from open_notebook.repo_kb.store import Store

SYSTEM = """你是 AV 影像系統的維運知識庫助理，工作目錄就是知識庫。
查找順序：
1. 先讀 wiki/index.md，再依連結讀 wiki/systems、wiki/modules、wiki/tables、wiki/rules、wiki/sop、wiki/discrepancies.md。
2. 需要證據或 wiki 不足時，用 Grep / Glob 在 mirror/ 搜尋原文（Word/Visio 原文為 .txt）。中文、錯誤碼、表名都可直接 Grep。
3. 檔案的 commit 可在 manifest.tsv 查到（欄位：repo、path、mirror、last_commit）。
回答規則：
- 用繁體中文，先給結論，再列依據。
- 每一項依據都附引文，格式嚴格為 〔repo:path#L起-L迄@commit〕，path 為原始 repo 路徑（不含 mirror/ 前綴、不含 .txt 後綴），行號為 mirror 檔案中的行號。
- 找不到證據就明說「知識庫中找不到」，不要臆測。
- <IP>、<ACCOUNT>、<SECRET>、<CONN> 是遮蔽標記，不要猜測原值。
- 只能讀取工作目錄內的檔案。"""

TOOLS = "Read,Grep,Glob"


def _deny_rules() -> List[str]:
    home = os.path.expanduser("~")
    rules = []
    for tool in ("Read", "Grep", "Glob"):
        rules += [
            f"{tool}(//{home.lstrip('/')}/Documents/Git_Repo/**)",
            f"{tool}(**/usr/**)",
            f"{tool}(//{home.lstrip('/')}/.ssh/**)",
            f"{tool}(//{home.lstrip('/')}/.claude/**)",
            f"{tool}(//{home.lstrip('/')}/.codex/**)",
        ]
    return rules


def _tool_paths(inp: Dict[str, Any]) -> List[str]:
    return [
        str(inp[k])
        for k in ("file_path", "path", "pattern", "glob")
        if k in inp and inp[k]
    ]


def ask(
    store: Store,
    question: str,
    model: Optional[str] = None,
    out: Optional[str] = None,
    timeout: float = 900,
) -> Dict[str, Any]:
    exe = resolve_executable("claude")
    if not exe:
        raise RuntimeError("claude CLI not found")
    data_dir = os.path.realpath(store.data_dir)
    fd, sys_file = tempfile.mkstemp(
        prefix=".agent-system-", suffix=".txt", dir=data_dir
    )
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SYSTEM)
    argv = [
        exe,
        "-p",
        "--output-format",
        "stream-json",
        "--verbose",
        "--tools",
        TOOLS,
        # No allow rules on purpose: read-only tools are allowed inside the
        # working directory by default; anything else needs approval, which
        # dontAsk turns into a denial. (Bare "Read" allow rules would permit
        # reads anywhere on disk.)
        "--disallowedTools",
        *_deny_rules(),
        "--permission-mode",
        "dontAsk",
        "--strict-mcp-config",
        "--setting-sources",
        "project",
        "--no-session-persistence",
        "--disable-slash-commands",
        "--system-prompt-file",
        sys_file,
    ]
    if model:
        argv += ["--model", model]
    started = time.monotonic()
    proc = _Proc(argv, cwd=data_dir)
    calls: List[Dict[str, Any]] = []
    denied = 0
    answer = ""
    usage: Dict[str, Any] = {}
    try:
        proc.write(question)
        proc.close_stdin()
        deadline = started + timeout
        while True:
            line = _next_line(proc, deadline, "Claude Code")
            if line is None:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("type") == "assistant":
                for block in (msg.get("message") or {}).get("content") or []:
                    if block.get("type") == "tool_use":
                        calls.append(
                            {
                                "tool": block.get("name"),
                                "args": _tool_paths(block.get("input") or {}),
                            }
                        )
            elif msg.get("type") == "user":
                for block in (msg.get("message") or {}).get("content") or []:
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("is_error")
                    ):
                        denied += 1
            elif msg.get("type") == "result":
                answer = msg.get("result") or ""
                usage = msg.get("usage") or {}
                break
        proc.p.wait(timeout=10)
    finally:
        proc.kill()
        os.unlink(sys_file)
    outside = []
    for c in calls:
        for a in c["args"]:
            p = a if os.path.isabs(a) else os.path.join(data_dir, a)
            if c["tool"] == "Read" and not os.path.realpath(p).startswith(
                data_dir + os.sep
            ):
                outside.append(a)
            if has_denied_component(a.rstrip("*/") + "/x"):
                outside.append(a)
    cites = validate_text(store, answer)
    detail = {
        "question_sha1": hashlib.sha1(question.encode()).hexdigest()[:12],
        "seconds": round(time.monotonic() - started, 1),
        "tool_calls": len(calls),
        "tool_errors_or_denials": denied,
        "paths": sorted({a for c in calls for a in c["args"]})[:80],
        "outside_or_denied_paths": outside,
        "citations": cites["by_result"],
        "usage": {k: v for k, v in usage.items() if isinstance(v, (int, float))},
    }
    store.event(
        "ask",
        "*",
        {k: v for k, v in detail.items() if k != "paths"}
        | {"path_count": len(detail["paths"])},
    )
    store.db.commit()
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "question": question,
                    "answer": answer,
                    **detail,
                    "bad_citations": cites["bad"],
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    return {"answer": answer, **detail}
