"""Detect installed local AI CLIs, their version and whether they are logged in.

Only non-sensitive fields are returned. Login probes never expose account
email, organisation or token data.
"""

import json
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

from open_notebook.ai.local_cli import CLAUDE_CODE, CODEX_CLI, DISPLAY_NAMES
from open_notebook.ai.local_cli.process import resolve_executable, run_short

_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")

# Model choices offered when registering a CLI-backed model. "default" lets the
# CLI use whatever model the user configured for it.
SUGGESTED_MODELS = {
    CLAUDE_CODE: ["default", "sonnet", "opus", "haiku"],
    CODEX_CLI: ["default"],
}


@dataclass
class CLIStatus:
    provider: str
    display_name: str
    installed: bool
    path: Optional[str] = None
    version: Optional[str] = None
    logged_in: Optional[bool] = None
    auth_method: Optional[str] = None
    plan: Optional[str] = None
    error: Optional[str] = None
    suggested_models: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _version(path: str) -> Optional[str]:
    try:
        out = run_short([path, "--version"], timeout=20)
        m = _VERSION_RE.search(out.stdout or out.stderr or "")
        return m.group(1) if m else None
    except Exception:
        return None


def detect_claude() -> CLIStatus:
    status = CLIStatus(
        provider=CLAUDE_CODE,
        display_name=DISPLAY_NAMES[CLAUDE_CODE],
        installed=False,
        suggested_models=SUGGESTED_MODELS[CLAUDE_CODE],
    )
    path = resolve_executable("claude")
    if not path:
        status.error = "claude not found on PATH"
        return status
    status.installed, status.path, status.version = True, path, _version(path)
    try:
        out = run_short([path, "auth", "status", "--json"], timeout=20)
        data = json.loads(out.stdout or "{}")
        status.logged_in = bool(data.get("loggedIn"))
        status.auth_method = data.get("authMethod")
        status.plan = data.get("subscriptionType")
    except Exception as e:  # unknown CLI version or unexpected output
        status.error = f"could not read login status: {type(e).__name__}"
    return status


def detect_codex() -> CLIStatus:
    status = CLIStatus(
        provider=CODEX_CLI,
        display_name=DISPLAY_NAMES[CODEX_CLI],
        installed=False,
        suggested_models=SUGGESTED_MODELS[CODEX_CLI],
    )
    path = resolve_executable("codex")
    if not path:
        status.error = "codex not found on PATH"
        return status
    status.installed, status.path, status.version = True, path, _version(path)
    try:
        out = run_short([path, "login", "status"], timeout=20)
        text = f"{out.stdout}\n{out.stderr}"
        status.logged_in = out.returncode == 0 and "logged in" in text.lower()
        lowered = text.lower()
        if "chatgpt" in lowered:
            status.auth_method = "chatgpt"
        elif "api key" in lowered:
            status.auth_method = "api_key"
    except Exception as e:
        status.error = f"could not read login status: {type(e).__name__}"
    return status


def detect_all() -> List[CLIStatus]:
    return [detect_claude(), detect_codex()]
