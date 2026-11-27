"""Locating CLI executables and building a clean subprocess environment.

Pattern borrowed from the Multica daemon: try PATH first, then ask the user's
login shell (GUI-launched or service-managed processes often miss nvm / fnm /
~/.local/bin PATH entries). The child inherits the user's environment so the
CLI finds its own login; we only strip markers that would make a CLI think it
is running nested inside another Claude Code session.
"""

import os
import re
import shutil
import subprocess
import time
from typing import Dict, List, Optional

_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_-]*$")
_SHELL_CACHE: Dict[str, tuple[float, Optional[str]]] = {}
_SHELL_TTL_SECONDS = 30 * 60

# Internal Claude Code session markers; never user configuration.
_FILTERED_ENV_KEYS = {
    "CLAUDECODE",
    "CLAUDE_CODE_ENTRYPOINT",
    "CLAUDE_CODE_EXECPATH",
    "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_SSE_PORT",
}

ENV_OVERRIDES = {
    "claude": "OPEN_NOTEBOOK_CLAUDE_PATH",
    "codex": "OPEN_NOTEBOOK_CODEX_PATH",
}


def _resolve_via_login_shell(name: str) -> Optional[str]:
    if not _SAFE_NAME.match(name):
        return None
    cached = _SHELL_CACHE.get(name)
    if cached and time.monotonic() - cached[0] < _SHELL_TTL_SECONDS:
        return cached[1]
    shell = os.environ.get("SHELL") or "/bin/sh"
    path: Optional[str] = None
    try:
        out = subprocess.run(
            [shell, "-lc", f"command -v {name}"],
            capture_output=True,
            text=True,
            timeout=10,
            env=child_env(),
        )
        candidate = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        if candidate.startswith("/") and os.access(candidate, os.X_OK):
            path = candidate
    except Exception:
        path = None
    _SHELL_CACHE[name] = (time.monotonic(), path)
    return path


def resolve_executable(name: str) -> Optional[str]:
    """Return an absolute path for the CLI, or None when it is not installed."""
    override = os.environ.get(ENV_OVERRIDES.get(name, ""), "").strip()
    if override:
        return override if os.access(override, os.X_OK) else None
    return shutil.which(name) or _resolve_via_login_shell(name)


def child_env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in _FILTERED_ENV_KEYS and not k.startswith("CLAUDECODE_")
    }
    if extra:
        env.update(extra)
    return env


def run_short(argv: List[str], timeout: float = 20) -> subprocess.CompletedProcess:
    """Run a short probe command (version / login status)."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=child_env(),
        stdin=subprocess.DEVNULL,
    )
