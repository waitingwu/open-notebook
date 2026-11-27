"""Failure taxonomy for local CLI runs and its mapping onto typed API errors."""

from enum import Enum

from open_notebook.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ExternalServiceError,
    OpenNotebookError,
    RateLimitError,
)


class LocalCLIFailure(str, Enum):
    CLI_MISSING = "cli_missing"
    NOT_LOGGED_IN = "not_logged_in"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CLI_ERROR = "cli_error"
    PARSE_ERROR = "parse_error"
    EMPTY_RESPONSE = "empty_response"
    CANCELLED = "cancelled"


_USER_MESSAGES = {
    LocalCLIFailure.CLI_MISSING: "{cli} was not found on this machine. Install it and make sure it is on PATH.",
    LocalCLIFailure.NOT_LOGGED_IN: "{cli} is not logged in. Run `{login}` in a terminal, then try again. Open Notebook does not switch to a paid API automatically.",
    LocalCLIFailure.RATE_LIMITED: "{cli} reports that your subscription usage limit has been reached. Wait for the limit to reset, then try again.",
    LocalCLIFailure.TIMEOUT: "{cli} did not finish in time.",
    LocalCLIFailure.CLI_ERROR: "{cli} failed: {detail}",
    LocalCLIFailure.PARSE_ERROR: "Could not read {cli} output (unsupported CLI version?): {detail}",
    LocalCLIFailure.EMPTY_RESPONSE: "{cli} returned an empty response.",
    LocalCLIFailure.CANCELLED: "{cli} run was cancelled.",
}

_LOGIN_COMMANDS = {"Claude Code": "claude auth login", "Codex": "codex login"}


class LocalCLIError(Exception):
    """Raised by the CLI runners; converted to a typed error at the model boundary."""

    def __init__(self, failure: LocalCLIFailure, cli: str, detail: str = ""):
        self.failure = failure
        self.cli = cli
        self.detail = detail
        super().__init__(self.user_message())

    def user_message(self) -> str:
        return _USER_MESSAGES[self.failure].format(
            cli=self.cli,
            login=_LOGIN_COMMANDS.get(self.cli, "login"),
            detail=self.detail[:300] or "unknown error",
        )

    def to_typed(self) -> OpenNotebookError:
        msg = self.user_message()
        if self.failure == LocalCLIFailure.NOT_LOGGED_IN:
            return AuthenticationError(msg)
        if self.failure == LocalCLIFailure.RATE_LIMITED:
            return RateLimitError(msg)
        if self.failure == LocalCLIFailure.CLI_MISSING:
            return ConfigurationError(msg)
        return ExternalServiceError(msg)
