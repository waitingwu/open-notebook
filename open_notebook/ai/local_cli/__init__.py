"""Local AI CLI runtimes (Claude Code, Codex) used as chat-model backends.

Open Notebook never reads, stores or forwards the CLIs' login credentials:
each CLI is spawned as a subprocess and authenticates itself with whatever
login already exists on this machine.
"""

from open_notebook.ai.local_cli.errors import LocalCLIError, LocalCLIFailure

CLAUDE_CODE = "claude_code"
CODEX_CLI = "codex_cli"
LOCAL_CLI_PROVIDERS = (CLAUDE_CODE, CODEX_CLI)

DISPLAY_NAMES = {
    CLAUDE_CODE: "Claude Code (local CLI)",
    CODEX_CLI: "Codex (local CLI)",
}


def is_local_cli_provider(provider: str | None) -> bool:
    return provider in LOCAL_CLI_PROVIDERS


__all__ = [
    "CLAUDE_CODE",
    "CODEX_CLI",
    "DISPLAY_NAMES",
    "LOCAL_CLI_PROVIDERS",
    "LocalCLIError",
    "LocalCLIFailure",
    "is_local_cli_provider",
]
