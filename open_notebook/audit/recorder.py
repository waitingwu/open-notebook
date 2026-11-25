"""Record every chat-model call into ai_run / ai_run_event / ai_usage.

Privacy rules (enforced here, the only writer):
- never store prompts, source text or model answers — only lengths and a
  SHA-256 of the prompt;
- never store credentials; error text is redacted and cut to its last 2 KB;
- source / notebook references are stored as record IDs only.

LLM callbacks fire from sync worker threads as well as the event loop, so
writes go through a dedicated background thread with its own event loop and
never block (or fail) the user's request.
"""

import asyncio
import hashlib
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from loguru import logger

from open_notebook.ai.local_cli import is_local_cli_provider
from open_notebook.audit.redact import redact_value, tail


class _AuditWriter:
    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

    def _ensure(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is None:
                loop = asyncio.new_event_loop()
                t = threading.Thread(
                    target=loop.run_forever, name="audit-writer", daemon=True
                )
                t.start()
                self._loop = loop
            return self._loop

    def submit(self, coro) -> None:
        fut = asyncio.run_coroutine_threadsafe(coro, self._ensure())
        fut.add_done_callback(_log_failure)

    def flush(self, timeout: float = 10) -> None:
        """Wait until everything submitted so far has been written (tests)."""
        fut = asyncio.run_coroutine_threadsafe(asyncio.sleep(0), self._ensure())
        fut.result(timeout)


def _log_failure(fut) -> None:
    exc = fut.exception()
    if exc:
        logger.warning(f"audit write failed: {type(exc).__name__}: {exc}")


writer = _AuditWriter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _prompt_stats(messages: List[List[Any]]) -> Dict[str, Any]:
    texts: List[str] = []
    for batch in messages:
        for m in batch:
            content = getattr(m, "content", "")
            texts.append(content if isinstance(content, str) else str(content))
    joined = "\n".join(texts)
    return {
        "prompt_chars": len(joined),
        "prompt_sha256": hashlib.sha256(joined.encode("utf-8")).hexdigest(),
    }


class AuditCallbackHandler(BaseCallbackHandler):
    """Attached to every provisioned chat model (see ai/provision.py)."""

    raise_error = False

    def __init__(
        self, provider: str, model_name: str, model_id: Optional[str], feature: str
    ):
        self.provider = provider
        self.model_name = model_name
        self.model_id = model_id
        self.feature = feature
        self._runs: Dict[UUID, Dict[str, Any]] = {}

    # LangChain chat models call on_chat_model_start, not on_llm_start.
    def on_chat_model_start(
        self, serialized, messages, *, run_id: UUID, metadata=None, **kwargs
    ):
        metadata = metadata or {}
        self._runs[run_id] = {
            "t0": time.monotonic(),
            "started_at": _now(),
            "first_token_ms": None,
            "response_chars": 0,
            "feature": metadata.get("audit_feature") or self.feature,
            "notebook_id": metadata.get("audit_notebook_id"),
            "source_ids": list(metadata.get("audit_source_ids") or []),
            **_prompt_stats(messages),
        }

    def on_llm_new_token(self, token: Any, *, run_id: UUID, **kwargs: Any) -> None:  # type: ignore[override]
        run = self._runs.get(run_id)
        if run is None:
            return
        if run["first_token_ms"] is None:
            run["first_token_ms"] = int((time.monotonic() - run["t0"]) * 1000)
        run["response_chars"] += len(token) if isinstance(token, str) else 0

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs):
        run = self._runs.pop(run_id, None)
        if run is None:
            return
        audit: Dict[str, Any] = {}
        usage: List[Dict[str, Any]] = []
        response_chars = 0
        for gens in response.generations:
            for g in gens:
                info = (g.generation_info or {}).get("local_cli_audit")
                msg = getattr(g, "message", None)
                if not info and msg is not None:
                    info = (getattr(msg, "response_metadata", {}) or {}).get(
                        "local_cli_audit"
                    )
                if info:
                    audit = info
                response_chars += len(getattr(g, "text", "") or "")
                um = getattr(msg, "usage_metadata", None) if msg is not None else None
                if um and not info:
                    details = um.get("input_token_details") or {}
                    usage.append(
                        {
                            "model": self.model_name,
                            "input_tokens": um.get("input_tokens", 0),
                            "output_tokens": um.get("output_tokens", 0),
                            "cache_read_tokens": details.get("cache_read", 0),
                            "cache_write_tokens": details.get("cache_creation", 0),
                            "reasoning_tokens": (
                                um.get("output_token_details") or {}
                            ).get("reasoning", 0),
                            "cost_usd": None,
                        }
                    )
        if audit:
            usage = audit.get("usage") or []
        run["response_chars"] = max(run["response_chars"], response_chars)
        self._submit(run, "success", None, None, audit, usage)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs):
        run = self._runs.pop(run_id, None)
        if run is None:
            return
        audit = getattr(error, "local_cli_audit", None) or {}
        reason = getattr(error, "local_cli_failure", None) or type(error).__name__
        detail = getattr(error, "local_cli_detail", None) or str(error)
        self._submit(run, "error", reason, detail, audit, audit.get("usage") or [])

    def _submit(self, run, status, reason, detail, audit, usage):
        ended = _now()
        error_message, truncated = tail(detail or "") if detail else (None, False)
        events = list(audit.get("events") or [])
        status_detail: Dict[str, Any] = {}
        for ev in events:
            if ev.get("name") == "cli_initialized":
                status_detail = ev.get("detail") or {}
        record = {
            "provider": self.provider,
            "model": status_detail.get("model") or self.model_name,
            "model_id": self.model_id,
            "feature": run["feature"],
            "notebook_id": run["notebook_id"],
            "source_ids": run["source_ids"],
            "status": status,
            "failure_reason": reason,
            "error_message": error_message,
            "error_truncated": truncated,
            "started_at": run["started_at"],
            "ended_at": ended,
            "duration_ms": int((time.monotonic() - run["t0"]) * 1000),
            "first_token_ms": run["first_token_ms"],
            "prompt_chars": run["prompt_chars"],
            "prompt_sha256": run["prompt_sha256"],
            "response_chars": run["response_chars"],
            "runtime": "local_cli" if is_local_cli_provider(self.provider) else "api",
            "cli_version": status_detail.get("cli_version"),
            "auth_mode": status_detail.get("auth_mode")
            or (
                "subscription"
                if status_detail.get("api_key_source") == "none"
                else status_detail.get("api_key_source")
            ),
        }
        writer.submit(
            persist_run(
                redact_value(record),
                [redact_value(e) for e in events],
                usage,
                audit.get("rate_limit"),
            )
        )


async def persist_run(
    record: Dict[str, Any],
    events: List[Dict[str, Any]],
    usage: List[Dict[str, Any]],
    rate_limit: Optional[Dict[str, Any]],
) -> None:
    from open_notebook.audit.pricing import estimate_cost
    from open_notebook.database.repository import (
        ensure_record_id,
        repo_create,
        repo_query,
    )

    totals = {
        k: 0
        for k in (
            "input_tokens",
            "output_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "reasoning_tokens",
        )
    }
    reported = 0.0
    has_reported = False
    estimated = 0.0
    has_estimate = False
    for u in usage:
        for k in totals:
            totals[k] += int(u.get(k) or 0)
        if u.get("cost_usd") is not None:
            reported += float(u["cost_usd"])
            has_reported = True
        est = await estimate_cost(u.get("model") or record["model"], u)
        if est is not None:
            estimated += est
            has_estimate = True
    record.update(totals)
    record["cost_usd_reported"] = round(reported, 6) if has_reported else None
    record["cost_usd_estimated"] = (
        round(reported, 6)
        if has_reported
        else (round(estimated, 6) if has_estimate else None)
    )
    created = await repo_create("ai_run", record)
    run = created[0] if isinstance(created, list) else created
    run_id = run["id"]
    for seq, ev in enumerate(events, start=1):
        await repo_create(
            "ai_run_event",
            {
                "run": ensure_record_id(run_id),
                "seq": seq,
                "type": ev.get("type"),
                "name": ev.get("name"),
                "detail": ev.get("detail") or {},
            },
        )
    for u in usage:
        await repo_create(
            "ai_usage",
            {
                "run": ensure_record_id(run_id),
                "provider": record["provider"],
                "model": u.get("model") or record["model"],
                "feature": record["feature"],
                "input_tokens": int(u.get("input_tokens") or 0),
                "output_tokens": int(u.get("output_tokens") or 0),
                "cache_read_tokens": int(u.get("cache_read_tokens") or 0),
                "cache_write_tokens": int(u.get("cache_write_tokens") or 0),
                "reasoning_tokens": int(u.get("reasoning_tokens") or 0),
                "cost_usd_reported": u.get("cost_usd"),
            },
        )
    if rate_limit:
        await repo_query(
            "UPSERT type::thing('ai_rate_limit', $provider) CONTENT {provider: $provider, snapshot: $snapshot, observed_at: time::now()}",
            {"provider": record["provider"], "snapshot": rate_limit},
        )
