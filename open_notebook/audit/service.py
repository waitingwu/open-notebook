"""Audit queries: run list / detail, usage summary, rate limits, export,
settings, retention clean-up and clear-all."""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from open_notebook.database.repository import ensure_record_id, repo_query

SETTINGS_ID = "open_notebook:audit_settings"
DEFAULT_SETTINGS: Dict[str, Any] = {
    "event_retention_days": 30,
    "run_retention_days": 365,
    "pricing": {},
}

RUN_LIST_FIELDS = (
    "id, provider, model, feature, status, failure_reason, runtime, started_at, "
    "duration_ms, first_token_ms, input_tokens, output_tokens, cache_read_tokens, "
    "cache_write_tokens, reasoning_tokens, cost_usd_estimated, cost_usd_reported, "
    "notebook_id, source_ids"
)
EXPORT_FIELDS = [
    "id",
    "started_at",
    "ended_at",
    "provider",
    "model",
    "runtime",
    "feature",
    "status",
    "failure_reason",
    "duration_ms",
    "first_token_ms",
    "prompt_chars",
    "response_chars",
    "input_tokens",
    "output_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
    "cost_usd_reported",
    "cost_usd_estimated",
    "cli_version",
    "auth_mode",
    "notebook_id",
    "source_ids",
]


def _first(rows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return rows[0] if rows else None


async def get_audit_settings() -> Dict[str, Any]:
    row = _first(await repo_query(f"SELECT * FROM {SETTINGS_ID}"))
    merged = dict(DEFAULT_SETTINGS)
    if row:
        for k in DEFAULT_SETTINGS:
            if row.get(k) is not None:
                merged[k] = row[k]
    return merged


async def update_audit_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    current = await get_audit_settings()
    current.update(
        {k: v for k, v in patch.items() if k in DEFAULT_SETTINGS and v is not None}
    )
    await repo_query(f"UPSERT {SETTINGS_ID} CONTENT $data", {"data": current})
    return current


def _filters(
    provider: Optional[str],
    status: Optional[str],
    feature: Optional[str],
    since: Optional[datetime],
) -> tuple[str, Dict[str, Any]]:
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    if provider:
        clauses.append("provider = $provider")
        params["provider"] = provider
    if status:
        clauses.append("status = $status")
        params["status"] = status
    if feature:
        clauses.append("feature = $feature")
        params["feature"] = feature
    if since:
        clauses.append("started_at >= $since")
        params["since"] = since
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


async def list_runs(
    limit: int = 50,
    offset: int = 0,
    provider: Optional[str] = None,
    status: Optional[str] = None,
    feature: Optional[str] = None,
) -> Dict[str, Any]:
    where, params = _filters(provider, status, feature, None)
    params.update({"limit": limit, "offset": offset})
    rows = await repo_query(
        f"SELECT {RUN_LIST_FIELDS} FROM ai_run{where} ORDER BY started_at DESC LIMIT $limit START $offset",
        params,
    )
    count = _first(
        await repo_query(f"SELECT count() AS n FROM ai_run{where} GROUP ALL", params)
    )
    return {"items": rows, "total": (count or {}).get("n", 0)}


async def get_run(run_id: str) -> Optional[Dict[str, Any]]:
    rid = ensure_record_id(
        run_id if run_id.startswith("ai_run:") else f"ai_run:{run_id}"
    )
    run = _first(await repo_query("SELECT * FROM $rid", {"rid": rid}))
    if not run:
        return None
    run["events"] = await repo_query(
        "SELECT seq, type, name, detail, created FROM ai_run_event WHERE run = $rid ORDER BY seq",
        {"rid": rid},
    )
    run["usage"] = await repo_query(
        "SELECT model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens, cost_usd_reported FROM ai_usage WHERE run = $rid",
        {"rid": rid},
    )
    return run


async def usage_summary(days: int = 30) -> Dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await repo_query(
        "SELECT provider, model, feature, status, input_tokens, output_tokens, cache_read_tokens, "
        "cache_write_tokens, reasoning_tokens, cost_usd_estimated, started_at FROM ai_run "
        "WHERE started_at >= $since",
        {"since": since},
    )
    token_keys = (
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "reasoning_tokens",
    )

    def blank() -> Dict[str, Any]:
        return {
            **{k: 0 for k in token_keys},
            "runs": 0,
            "errors": 0,
            "cost_usd_estimated": 0.0,
            "uncosted_runs": 0,
        }

    totals = blank()
    by_day: Dict[str, Dict[str, Any]] = {}
    by_model: Dict[str, Dict[str, Any]] = {}
    by_feature: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        started = r.get("started_at")
        day = (
            (started if isinstance(started, str) else started.isoformat())[:10]
            if started
            else "unknown"
        )
        model_key = f"{r.get('provider')} · {r.get('model')}"
        for bucket in (
            totals,
            by_day.setdefault(day, blank()),
            by_model.setdefault(model_key, blank()),
            by_feature.setdefault(r.get("feature") or "unknown", blank()),
        ):
            bucket["runs"] += 1
            if r.get("status") == "error":
                bucket["errors"] += 1
            for k in token_keys:
                bucket[k] += int(r.get(k) or 0)
            if r.get("cost_usd_estimated") is None:
                bucket["uncosted_runs"] += 1
            else:
                bucket["cost_usd_estimated"] += float(r["cost_usd_estimated"])
    # Fill empty days so the chart has a continuous axis.
    today = datetime.now(timezone.utc).date()
    daily = []
    for i in range(days - 1, -1, -1):
        d = (today - timedelta(days=i)).isoformat()
        daily.append({"date": d, **by_day.get(d, blank())})
    return {
        "days": days,
        "totals": totals,
        "daily": daily,
        "by_model": [{"key": k, **v} for k, v in sorted(by_model.items())],
        "by_feature": [{"key": k, **v} for k, v in sorted(by_feature.items())],
    }


async def rate_limits() -> List[Dict[str, Any]]:
    return await repo_query(
        "SELECT provider, snapshot, observed_at FROM ai_rate_limit ORDER BY provider"
    )


async def export_runs(fmt: str, days: int) -> tuple[str, str]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await repo_query(
        f"SELECT {', '.join(EXPORT_FIELDS)} FROM ai_run WHERE started_at >= $since ORDER BY started_at DESC",
        {"since": since},
    )
    if fmt == "json":
        return json.dumps(
            rows, default=str, ensure_ascii=False, indent=2
        ), "application/json"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_FIELDS, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        r = dict(r)
        r["source_ids"] = ";".join(r.get("source_ids") or [])
        w.writerow(r)
    return buf.getvalue(), "text/csv"


async def apply_retention() -> Dict[str, int]:
    settings = await get_audit_settings()
    now = datetime.now(timezone.utc)
    ev_cut = now - timedelta(days=int(settings["event_retention_days"]))
    run_cut = now - timedelta(days=int(settings["run_retention_days"]))
    ev = await repo_query(
        "DELETE ai_run_event WHERE created < $cut RETURN BEFORE", {"cut": ev_cut}
    )
    old_runs = await repo_query(
        "SELECT VALUE id FROM ai_run WHERE started_at < $cut", {"cut": run_cut}
    )
    if old_runs:
        await repo_query("DELETE ai_run_event WHERE run INSIDE $ids", {"ids": old_runs})
        await repo_query("DELETE ai_usage WHERE run INSIDE $ids", {"ids": old_runs})
        await repo_query("DELETE ai_run WHERE id INSIDE $ids", {"ids": old_runs})
    result = {"events_deleted": len(ev or []), "runs_deleted": len(old_runs or [])}
    logger.info(f"audit retention applied: {result}")
    return result


async def clear_all() -> None:
    await repo_query(
        "DELETE ai_run_event; DELETE ai_usage; DELETE ai_run; DELETE ai_rate_limit;"
    )


async def detach_notebook(notebook_id: str) -> None:
    """On notebook deletion: drop its run events, keep anonymous usage."""
    nb = str(notebook_id)
    runs = await repo_query(
        "SELECT VALUE id FROM ai_run WHERE notebook_id = $nb", {"nb": nb}
    )
    if runs:
        await repo_query("DELETE ai_run_event WHERE run INSIDE $ids", {"ids": runs})
        await repo_query(
            "UPDATE ai_run SET notebook_id = NONE, source_ids = [] WHERE id INSIDE $ids",
            {"ids": runs},
        )
