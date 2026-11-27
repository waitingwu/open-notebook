"""Local CLI runtime: protocol parsing against recorded (sanitized) CLI output,
prompt assembly, error mapping, and audit redaction."""

import json
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from open_notebook.ai.local_cli.chat_model import _merge_rate_limit, messages_to_prompt
from open_notebook.ai.local_cli.errors import LocalCLIError, LocalCLIFailure
from open_notebook.ai.local_cli.parsing import (
    classify_error_text,
    parse_claude_line,
    parse_codex_notification,
)
from open_notebook.audit.redact import redact_text, tail
from open_notebook.exceptions import (
    AuthenticationError,
    ConfigurationError,
    RateLimitError,
)

FIXTURES = Path(__file__).parent / "fixtures" / "local_cli"


def _events(kind, events):
    return [e for e in events if e["kind"] == kind]


def test_claude_stream_json_fixture():
    events = []
    for line in (FIXTURES / "claude_stream_json.jsonl").read_text().splitlines():
        events += parse_claude_line(json.loads(line))
    assert "".join(e["text"] for e in _events("text", events)) == "OK"
    init = [e for e in events if e.get("name") == "cli_initialized"][0]
    assert init["detail"]["api_key_source"] == "none"  # subscription login
    assert init["detail"]["tool_count"] == 0
    (usage,) = _events("usage", events)
    assert usage["model"] == "claude-opus-5-5"
    assert usage["output_tokens"] == 5
    assert usage["cache_write_tokens"] > 0
    assert usage["cost_usd"] > 0
    (rl,) = _events("rate_limit", events)
    names = {w["name"] for w in rl["snapshot"]["windows"]}
    assert names == {"five_hour", "seven_day"}
    assert all(0 <= w["used_percent"] <= 100 for w in rl["snapshot"]["windows"])
    assert _events("done", events)[0]["text"] == "OK"
    assert not _events("error", events)


def test_codex_app_server_fixture():
    events = []
    for line in (FIXTURES / "codex_app_server.jsonl").read_text().splitlines():
        msg = json.loads(line)
        if msg.get("dir") == "in" and msg.get("method"):
            events += parse_codex_notification(msg["method"], msg.get("params") or {})
    assert "".join(e["text"] for e in _events("text", events)) == "OK"
    (usage,) = _events("usage", events)
    assert usage["input_tokens"] > 0 and usage["output_tokens"] == 5
    (rl,) = _events("rate_limit", events)
    assert rl["snapshot"]["plan"] == "business"
    assert rl["snapshot"]["status"] == "allowed"
    assert _events("done", events)[0]["text"] == "OK"


def test_claude_error_result_is_classified():
    msg = {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    }
    (err,) = _events("error", parse_claude_line(msg))
    assert err["reason"] == "not_logged_in"


def test_classify_error_text():
    assert (
        classify_error_text("Claude AI usage limit reached|1700000000")
        == "rate_limited"
    )
    assert classify_error_text("unexpected status 401 Unauthorized") == "not_logged_in"
    assert classify_error_text("boom") == "cli_error"


def test_error_mapping_to_typed_exceptions():
    assert isinstance(
        LocalCLIError(LocalCLIFailure.NOT_LOGGED_IN, "Codex").to_typed(),
        AuthenticationError,
    )
    assert isinstance(
        LocalCLIError(LocalCLIFailure.RATE_LIMITED, "Codex").to_typed(), RateLimitError
    )
    assert isinstance(
        LocalCLIError(LocalCLIFailure.CLI_MISSING, "Codex").to_typed(),
        ConfigurationError,
    )
    msg = LocalCLIError(LocalCLIFailure.NOT_LOGGED_IN, "Claude Code").user_message()
    assert "claude auth login" in msg and "paid API" in msg


def test_messages_to_prompt():
    system, prompt = messages_to_prompt(
        [SystemMessage(content="SYS"), HumanMessage(content="Q1")]
    )
    assert system == "SYS" and prompt == "Q1"
    system, prompt = messages_to_prompt(
        [
            SystemMessage(content="SYS"),
            HumanMessage(content="Q1"),
            AIMessage(content="A1"),
            HumanMessage(content="Q2"),
        ]
    )
    assert "User: Q1" in prompt and "Assistant: A1" in prompt and prompt.endswith("Q2")


def test_rate_limit_merge_keeps_windows():
    old = {"plan": "business", "status": "allowed", "windows": [{"name": "individual"}]}
    new: dict = {"plan": None, "status": "allowed", "windows": []}
    merged = _merge_rate_limit(old, new)
    assert merged["windows"] == old["windows"] and merged["plan"] == "business"


def test_redaction():
    text = "key sk-abcdefghijklmnopqrstuvwxyz123 by someone@example.com Bearer abcdefghijklmnopqrstu"
    out = redact_text(text)
    assert (
        "sk-abc" not in out
        and "someone@" not in out
        and "abcdefghijklmnopqrstu" not in out
    )
    long_text = "x" * 5000 + "END"
    cut, truncated = tail(long_text)
    assert truncated and cut.endswith("END") and len(cut.encode()) <= 2048


def test_audit_handler_never_records_prompt_or_answer(monkeypatch):
    """The audit record holds lengths and a hash only, never the text."""
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    from open_notebook.audit import recorder

    captured: dict = {}

    def fake_persist(record, events, usage, rate_limit):
        captured.update(record=record, events=events)

        async def _noop():
            return None

        return _noop()

    monkeypatch.setattr(recorder, "persist_run", fake_persist)
    monkeypatch.setattr(recorder.writer, "submit", lambda coro: coro.close())
    model = FakeListChatModel(responses=["SECRET-ANSWER-TEXT"])
    model.callbacks = [
        recorder.AuditCallbackHandler("fake", "fake-model", None, "chat")
    ]
    model.invoke(
        [HumanMessage(content="CONFIDENTIAL-SOURCE-TEXT sk-abcdefghijklmnopqrstuvwxyz")]
    )

    dumped = json.dumps(captured, default=str)
    assert "CONFIDENTIAL-SOURCE-TEXT" not in dumped
    assert "SECRET-ANSWER-TEXT" not in dumped
    assert "sk-abc" not in dumped
    rec = captured["record"]
    assert rec["status"] == "success" and rec["prompt_chars"] > 0
    assert len(rec["prompt_sha256"]) == 64
