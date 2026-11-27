"""Spawn the local CLIs and yield normalized events (see parsing.py).

Runners are synchronous generators: the LangChain chat model drives them from
a worker thread (LangGraph's sync checkpointed graphs) or via
`asyncio.to_thread` for async callers.

Safety defaults, since source text may contain prompt injection:
- Claude Code: `--tools ""` (no built-in tools), `--strict-mcp-config` (no MCP
  servers), `--setting-sources project` inside an empty temp dir (no user hooks
  or plugins), `--no-session-persistence`.
- Codex: read-only sandbox, approval policy "never", ephemeral thread, empty
  temp working directory.
Prompts are passed over stdin / a temp file that is deleted afterwards, never
in argv (argv is visible to other local users via `ps`).
"""

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

from open_notebook.ai.local_cli import CLAUDE_CODE, CODEX_CLI
from open_notebook.ai.local_cli.errors import LocalCLIError, LocalCLIFailure
from open_notebook.ai.local_cli.parsing import (
    Event,
    classify_error_text,
    normalize_codex_rate_limit,
    parse_claude_line,
    parse_codex_notification,
)
from open_notebook.ai.local_cli.process import child_env, resolve_executable

DEFAULT_TIMEOUT_SECONDS = float(
    os.environ.get("OPEN_NOTEBOOK_LOCAL_CLI_TIMEOUT", "600")
)
_STDERR_TAIL = 4000


class _Proc:
    """Subprocess with a line queue for stdout and a bounded stderr tail."""

    def __init__(self, argv: List[str], cwd: str):
        self.p = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=cwd,
            env=child_env(),
            bufsize=1,
            start_new_session=True,
        )
        self.lines: "queue.Queue[Optional[str]]" = queue.Queue()
        self.stderr = ""
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()

    def _read_out(self) -> None:
        assert self.p.stdout
        for line in self.p.stdout:
            self.lines.put(line)
        self.lines.put(None)

    def _read_err(self) -> None:
        assert self.p.stderr
        for line in self.p.stderr:
            self.stderr = (self.stderr + line)[-_STDERR_TAIL:]

    def write(self, data: str) -> None:
        assert self.p.stdin
        self.p.stdin.write(data)
        self.p.stdin.flush()

    def close_stdin(self) -> None:
        try:
            if self.p.stdin:
                self.p.stdin.close()
        except Exception:
            pass

    def kill(self) -> None:
        if self.p.poll() is None:
            try:
                os.killpg(self.p.pid, 15)
            except Exception:
                self.p.terminate()
            try:
                self.p.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(self.p.pid, 9)
                except Exception:
                    self.p.kill()


def _next_line(proc: _Proc, deadline: float, cli: str) -> Optional[str]:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise LocalCLIError(LocalCLIFailure.TIMEOUT, cli)
    try:
        return proc.lines.get(timeout=remaining)
    except queue.Empty:
        raise LocalCLIError(LocalCLIFailure.TIMEOUT, cli)


def _require(name: str, cli: str) -> str:
    path = resolve_executable(name)
    if not path:
        raise LocalCLIError(LocalCLIFailure.CLI_MISSING, cli)
    return path


# --------------------------------------------------------------------------
# Claude Code
# --------------------------------------------------------------------------


def run_claude(
    system_prompt: str,
    prompt: str,
    model: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[Event]:
    cli = "Claude Code"
    path = _require("claude", cli)
    workdir = tempfile.mkdtemp(prefix="on-claude-")
    try:
        sys_file = os.path.join(workdir, ".system-prompt.txt")
        with open(sys_file, "w", encoding="utf-8") as f:
            f.write(system_prompt or "You are a helpful assistant.")
        argv = [
            path,
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--tools",
            "",
            "--strict-mcp-config",
            "--setting-sources",
            "project",
            "--no-session-persistence",
            "--disable-slash-commands",
            "--system-prompt-file",
            sys_file,
        ]
        if model and model != "default":
            argv += ["--model", model]
        started = time.monotonic()
        proc = _Proc(argv, cwd=workdir)
        yield {
            "kind": "status",
            "name": "cli_started",
            "detail": {"provider": CLAUDE_CODE},
        }
        try:
            proc.write(prompt)
            proc.close_stdin()
            deadline = started + timeout
            saw_text = False
            finished = False
            while True:
                line = _next_line(proc, deadline, cli)
                if line is None:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # non-protocol noise
                for ev in parse_claude_line(msg):
                    if ev["kind"] == "text" and not saw_text:
                        saw_text = True
                        yield {
                            "kind": "status",
                            "name": "first_token",
                            "detail": {
                                "latency_ms": int((time.monotonic() - started) * 1000)
                            },
                        }
                    if ev["kind"] == "error":
                        raise LocalCLIError(
                            LocalCLIFailure(ev["reason"]), cli, ev["message"]
                        )
                    if ev["kind"] == "done":
                        finished = True
                    yield ev
            proc.p.wait(timeout=10)
            if not finished:
                tail = proc.stderr.strip()
                reason = classify_error_text(tail)
                raise LocalCLIError(
                    LocalCLIFailure(reason) if tail else LocalCLIFailure.PARSE_ERROR,
                    cli,
                    tail or f"exit code {proc.p.returncode} without a result event",
                )
        finally:
            proc.kill()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


# --------------------------------------------------------------------------
# Codex (app-server JSON-RPC over stdio)
# --------------------------------------------------------------------------


class _CodexRPC:
    def __init__(self, proc: _Proc, deadline: float, cli: str):
        self.proc, self.deadline, self.cli = proc, deadline, cli
        self.next_id = 0
        self.pending_notifications: List[Dict[str, Any]] = []

    def send(
        self, method: str, params: Any = None, notify: bool = False
    ) -> Optional[int]:
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if not notify:
            self.next_id += 1
            msg["id"] = self.next_id
        self.proc.write(json.dumps(msg) + "\n")
        return msg.get("id")

    def read(self) -> Optional[Dict[str, Any]]:
        while True:
            line = _next_line(self.proc, self.deadline, self.cli)
            if line is None:
                return None
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

    def request(self, method: str, params: Any = None) -> Dict[str, Any]:
        rid = self.send(method, params)
        while True:
            msg = self.read()
            if msg is None:
                tail = self.proc.stderr.strip()
                raise LocalCLIError(
                    LocalCLIFailure(classify_error_text(tail))
                    if tail
                    else LocalCLIFailure.CLI_ERROR,
                    self.cli,
                    tail or f"app-server exited during {method}",
                )
            if msg.get("id") == rid and "method" not in msg:
                if "error" in msg:
                    text = str((msg["error"] or {}).get("message") or msg["error"])
                    raise LocalCLIError(
                        LocalCLIFailure(classify_error_text(text)), self.cli, text
                    )
                return msg.get("result") or {}
            if "method" in msg and "id" in msg:
                self._decline(msg)
            elif "method" in msg:
                self.pending_notifications.append(msg)

    def _decline(self, msg: Dict[str, Any]) -> None:
        """Server-initiated requests (approvals, elicitation): always decline."""
        self.proc.write(
            json.dumps(
                {"jsonrpc": "2.0", "id": msg["id"], "result": {"decision": "decline"}}
            )
            + "\n"
        )


def run_codex(
    system_prompt: str,
    prompt: str,
    model: Optional[str] = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Iterator[Event]:
    cli = "Codex"
    path = _require("codex", cli)
    workdir = tempfile.mkdtemp(prefix="on-codex-")
    started = time.monotonic()
    proc = _Proc([path, "app-server", "--listen", "stdio://"], cwd=workdir)
    try:
        yield {
            "kind": "status",
            "name": "cli_started",
            "detail": {"provider": CODEX_CLI},
        }
        rpc = _CodexRPC(proc, started + timeout, cli)
        init = rpc.request(
            "initialize",
            {
                "clientInfo": {
                    "name": "open-notebook",
                    "title": "Open Notebook",
                    "version": "1",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        rpc.send("initialized", notify=True)
        account = rpc.request("account/read", {"refreshToken": False})
        if not account.get("account") and account.get("requiresOpenaiAuth", True):
            raise LocalCLIError(LocalCLIFailure.NOT_LOGGED_IN, cli, "no account")
        try:
            limits = rpc.request("account/rateLimits/read")
            if limits.get("rateLimits"):
                yield {
                    "kind": "rate_limit",
                    "snapshot": normalize_codex_rate_limit(limits["rateLimits"]),
                }
        except LocalCLIError:
            pass  # optional; older CLIs may not implement it
        start_params: Dict[str, Any] = {
            "cwd": workdir,
            "sandbox": "read-only",
            "approvalPolicy": "never",
            "ephemeral": True,
            "developerInstructions": (system_prompt or "")
            + "\n\nAnswer directly in text. Do not run commands, read files or call tools.",
        }
        if model and model != "default":
            start_params["model"] = model
        thread = rpc.request("thread/start", start_params)
        thread_id = (thread.get("thread") or {}).get("id")
        resolved_model = thread.get("model") or model
        yield {
            "kind": "status",
            "name": "cli_initialized",
            "detail": {
                "model": resolved_model,
                "cli_version": (thread.get("thread") or {}).get("cliVersion")
                or (init.get("userAgent") or "").split(" ")[0].split("/")[-1],
                "auth_mode": (account.get("account") or {}).get("type"),
            },
        }
        rpc.request(
            "turn/start",
            {"threadId": thread_id, "input": [{"type": "text", "text": prompt}]},
        )
        saw_text = False
        last_usage: Optional[Event] = None
        backlog = list(rpc.pending_notifications)
        rpc.pending_notifications.clear()
        while True:
            msg = backlog.pop(0) if backlog else rpc.read()
            if msg is None:
                tail = proc.stderr.strip()
                raise LocalCLIError(
                    LocalCLIFailure(classify_error_text(tail))
                    if tail
                    else LocalCLIFailure.CLI_ERROR,
                    cli,
                    tail or "app-server exited before the turn completed",
                )
            if "method" in msg and "id" in msg:
                rpc._decline(msg)
                continue
            method = msg.get("method")
            if not method:
                continue
            for ev in parse_codex_notification(method, msg.get("params") or {}):
                if ev["kind"] == "text" and not saw_text:
                    saw_text = True
                    yield {
                        "kind": "status",
                        "name": "first_token",
                        "detail": {
                            "latency_ms": int((time.monotonic() - started) * 1000)
                        },
                    }
                if ev["kind"] == "usage":
                    ev["model"] = resolved_model
                    last_usage = ev  # cumulative; emit once at the end
                    continue
                if ev["kind"] == "error":
                    raise LocalCLIError(
                        LocalCLIFailure(ev["reason"]), cli, ev["message"]
                    )
                if ev["kind"] == "done":
                    if last_usage:
                        yield last_usage
                    # Give a trailing rate-limit notification a moment to land.
                    yield ev
                    return
                yield ev
    finally:
        proc.close_stdin()
        proc.kill()
        shutil.rmtree(workdir, ignore_errors=True)


RUNNERS = {CLAUDE_CODE: run_claude, CODEX_CLI: run_codex}
