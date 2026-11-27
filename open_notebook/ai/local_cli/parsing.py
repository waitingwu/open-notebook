"""Pure parsers that turn raw CLI protocol messages into normalized events.

Kept free of I/O so they can be regression-tested against recorded fixtures
(tests/fixtures/local_cli/*.jsonl) whenever a CLI release changes its output.

Normalized event kinds:
  text        {"text"}
  usage       {"model", "input_tokens", "output_tokens", "cache_read_tokens",
               "cache_write_tokens", "reasoning_tokens", "cost_usd"}
  rate_limit  {"snapshot": {...}}  (see normalize_* below)
  status      {"name", "detail"}
  error       {"reason", "message"}
  done        {"text"}  final full text when the CLI reports it
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

Event = Dict[str, Any]

_LOGIN_HINTS = (
    "not logged in",
    "please run /login",
    "invalid api key",
    "oauth token has expired",
    "authentication_error",
    "please log in",
    "401",
)
_RATE_HINTS = ("usage limit", "rate limit", "rate_limit", "limit reached", "429")


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
    except Exception:
        return None


def classify_error_text(text: str) -> str:
    lowered = (text or "").lower()
    if any(h in lowered for h in _LOGIN_HINTS):
        return "not_logged_in"
    if any(h in lowered for h in _RATE_HINTS):
        return "rate_limited"
    return "cli_error"


# --------------------------------------------------------------------------
# Claude Code: `claude -p --output-format stream-json --verbose
#              --include-partial-messages`
# --------------------------------------------------------------------------


def normalize_claude_rate_limit(info: Dict[str, Any]) -> Dict[str, Any]:
    windows: List[Dict[str, Any]] = []
    for name, w in (info.get("unifiedWindows") or {}).items():
        util = w.get("utilization")
        windows.append(
            {
                "name": name,
                "used_percent": round(util * 100, 1)
                if isinstance(util, (int, float))
                else None,
                "resets_at": _iso(w.get("resetsAt")),
                "status": w.get("status"),
            }
        )
    if not windows and info.get("rateLimitType"):
        windows.append(
            {
                "name": info.get("rateLimitType"),
                "used_percent": None,
                "resets_at": _iso(info.get("resetsAt")),
                "status": info.get("status"),
            }
        )
    return {
        "plan": None,
        "status": info.get("status"),
        "windows": windows,
        "credits": {"overage_status": info.get("overageStatus")},
    }


def parse_claude_line(msg: Dict[str, Any]) -> List[Event]:
    t = msg.get("type")
    out: List[Event] = []
    if t == "system" and msg.get("subtype") == "init":
        out.append(
            {
                "kind": "status",
                "name": "cli_initialized",
                "detail": {
                    "model": msg.get("model"),
                    "cli_version": msg.get("claude_code_version"),
                    # "none" means the CLI's own subscription login is used.
                    "api_key_source": msg.get("apiKeySource"),
                    "tool_count": len(msg.get("tools") or []),
                },
            }
        )
    elif t == "stream_event":
        ev = msg.get("event") or {}
        if ev.get("type") == "content_block_delta":
            delta = ev.get("delta") or {}
            if delta.get("type") == "text_delta" and delta.get("text"):
                out.append({"kind": "text", "text": delta["text"]})
    elif t == "rate_limit_event":
        out.append(
            {
                "kind": "rate_limit",
                "snapshot": normalize_claude_rate_limit(
                    msg.get("rate_limit_info") or {}
                ),
            }
        )
    elif t == "result":
        for model, u in (msg.get("modelUsage") or {}).items():
            out.append(
                {
                    "kind": "usage",
                    "model": model,
                    # Normalized: input_tokens = total prompt tokens incl. cache
                    # reads/writes (Claude reports them separately; Codex and
                    # LangChain already include them).
                    "input_tokens": int(u.get("inputTokens") or 0)
                    + int(u.get("cacheReadInputTokens") or 0)
                    + int(u.get("cacheCreationInputTokens") or 0),
                    "output_tokens": int(u.get("outputTokens") or 0),
                    "cache_read_tokens": int(u.get("cacheReadInputTokens") or 0),
                    "cache_write_tokens": int(u.get("cacheCreationInputTokens") or 0),
                    "reasoning_tokens": int(u.get("thinkingTokens") or 0),
                    # List-price equivalent reported by the CLI; under a
                    # subscription this is not what the user pays.
                    "cost_usd": u.get("costUSD"),
                }
            )
        if msg.get("is_error") or msg.get("subtype") not in (None, "success"):
            text = str(msg.get("result") or msg.get("subtype") or "error")
            out.append(
                {"kind": "error", "reason": classify_error_text(text), "message": text}
            )
        else:
            out.append({"kind": "done", "text": msg.get("result") or ""})
    return out


# --------------------------------------------------------------------------
# Codex: `codex app-server --listen stdio://` (JSON-RPC notifications)
# --------------------------------------------------------------------------


def normalize_codex_rate_limit(rl: Dict[str, Any]) -> Dict[str, Any]:
    windows: List[Dict[str, Any]] = []
    for name in ("primary", "secondary"):
        w = rl.get(name)
        if isinstance(w, dict):
            mins = w.get("windowDurationMins")
            windows.append(
                {
                    "name": f"{name} ({mins} min)" if mins else name,
                    "used_percent": w.get("usedPercent"),
                    "resets_at": _iso(w.get("resetsAt")),
                    "status": None,
                }
            )
    ind = rl.get("individualLimit")
    if isinstance(ind, dict):
        remaining = ind.get("remainingPercent")
        windows.append(
            {
                "name": "individual",
                "used_percent": (100 - remaining)
                if isinstance(remaining, (int, float))
                else None,
                "resets_at": _iso(ind.get("resetsAt")),
                "status": None,
            }
        )
    credits = rl.get("credits") or {}
    return {
        "plan": rl.get("planType"),
        "status": "rejected" if rl.get("rateLimitReachedType") else "allowed",
        "windows": windows,
        "credits": {
            "has_credits": credits.get("hasCredits"),
            "unlimited": credits.get("unlimited"),
        },
    }


def parse_codex_notification(method: str, params: Dict[str, Any]) -> List[Event]:
    out: List[Event] = []
    if method == "item/agentMessage/delta":
        if params.get("delta"):
            out.append({"kind": "text", "text": params["delta"]})
    elif method == "thread/tokenUsage/updated":
        last = (params.get("tokenUsage") or {}).get("total") or {}
        out.append(
            {
                "kind": "usage",
                "model": None,
                "input_tokens": int(last.get("inputTokens") or 0),
                "output_tokens": int(last.get("outputTokens") or 0),
                "cache_read_tokens": int(last.get("cachedInputTokens") or 0),
                "cache_write_tokens": int(last.get("cacheWriteInputTokens") or 0),
                "reasoning_tokens": int(last.get("reasoningOutputTokens") or 0),
                "cost_usd": None,
                "cumulative": True,
            }
        )
    elif method == "account/rateLimits/updated":
        out.append(
            {
                "kind": "rate_limit",
                "snapshot": normalize_codex_rate_limit(params.get("rateLimits") or {}),
            }
        )
    elif method == "item/started":
        item = params.get("item") or {}
        if item.get("type") not in (None, "userMessage", "agentMessage", "reasoning"):
            # Tool use (command, file change, MCP call ...). Name only.
            out.append(
                {
                    "kind": "status",
                    "name": "tool_use",
                    "detail": {"item_type": item.get("type")},
                }
            )
    elif method == "error":
        err = params.get("error") or {}
        text = str(err.get("message") or params)
        out.append(
            {"kind": "error", "reason": classify_error_text(text), "message": text}
        )
    elif method == "turn/completed":
        turn = params.get("turn") or {}
        if turn.get("status") == "failed" or turn.get("error"):
            err = turn.get("error") or {}
            text = str(err.get("message") or err or "turn failed")
            out.append(
                {"kind": "error", "reason": classify_error_text(text), "message": text}
            )
        else:
            text = "".join(
                i.get("text") or ""
                for i in (turn.get("items") or [])
                if i.get("type") == "agentMessage"
            )
            out.append({"kind": "done", "text": text})
    return out
