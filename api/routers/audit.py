"""AI audit log: runs, usage dashboard, rate limits, export, retention."""

from typing import Dict, Literal, Optional

from fastapi import APIRouter, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from open_notebook.audit import service
from open_notebook.exceptions import InvalidInputError, NotFoundError

router = APIRouter()


class ModelRate(BaseModel):
    input: float = Field(0, ge=0, description="USD per 1M input tokens")
    output: float = Field(0, ge=0, description="USD per 1M output tokens")
    cache_read: Optional[float] = Field(
        None, ge=0, description="USD per 1M cached input tokens"
    )


class AuditSettingsUpdate(BaseModel):
    event_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    run_retention_days: Optional[int] = Field(None, ge=1, le=3650)
    pricing: Optional[Dict[str, ModelRate]] = None


@router.get("/audit/runs")
async def list_runs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    provider: Optional[str] = None,
    status: Optional[Literal["success", "error"]] = None,
    feature: Optional[str] = None,
):
    return await service.list_runs(limit, offset, provider, status, feature)


@router.get("/audit/runs/{run_id}")
async def get_run(run_id: str):
    run = await service.get_run(run_id)
    if not run:
        raise NotFoundError("Run not found")
    return run


@router.get("/audit/usage")
async def usage(days: int = Query(30, ge=1, le=365)):
    return await service.usage_summary(days)


@router.get("/audit/rate-limits")
async def rate_limits():
    return await service.rate_limits()


@router.get("/audit/export")
async def export(
    format: Literal["csv", "json"] = "csv", days: int = Query(365, ge=1, le=3650)
):
    body, media_type = await service.export_runs(format, days)
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="ai-runs.{format}"'},
    )


@router.get("/audit/settings")
async def get_settings():
    return await service.get_audit_settings()


@router.put("/audit/settings")
async def update_settings(update: AuditSettingsUpdate):
    patch = update.model_dump(exclude_none=True)
    if "pricing" in patch:
        patch["pricing"] = {
            k.strip(): v for k, v in patch["pricing"].items() if k and k.strip()
        }
    if (
        patch.get("event_retention_days")
        and patch.get("run_retention_days")
        and patch["event_retention_days"] > patch["run_retention_days"]
    ):
        raise InvalidInputError("Event retention cannot exceed run retention")
    return await service.update_audit_settings(patch)


@router.post("/audit/retention/apply")
async def apply_retention():
    return await service.apply_retention()


@router.delete("/audit/logs")
async def clear_logs():
    await service.clear_all()
    return {"success": True}
