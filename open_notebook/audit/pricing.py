"""API-equivalent cost estimation.

Subscription runs are not billed per token, so any figure here is an
*estimate of what the same tokens would cost on the pay-as-you-go API*.
Claude Code reports its own list-price figure (costUSD); for everything else
the user enters per-model rates (USD per 1M tokens) on the audit settings
page. No rates are shipped built in, because prices change and a stale
built-in table would silently mislead.
"""

from typing import Any, Dict, Optional


async def estimate_cost(model: Optional[str], usage: Dict[str, Any]) -> Optional[float]:
    if usage.get("cost_usd") is not None:
        return float(usage["cost_usd"])
    if not model:
        return None
    from open_notebook.audit.service import get_audit_settings

    settings = await get_audit_settings()
    rate = (settings.get("pricing") or {}).get(model)
    if not rate:
        return None
    per_m = 1_000_000
    inp = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cache_read_tokens") or 0)
    # input_tokens is normalized to include cache reads and writes.
    written = int(usage.get("cache_write_tokens") or 0)
    uncached = max(inp - cached - written, 0)
    return (
        uncached * float(rate.get("input") or 0)
        + cached * float(rate.get("cache_read") or rate.get("input") or 0)
        + written * float(rate.get("input") or 0)
        + int(usage.get("output_tokens") or 0) * float(rate.get("output") or 0)
    ) / per_m
