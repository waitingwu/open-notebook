"""Local AI CLI runtimes: detection and model registration."""

import asyncio
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from open_notebook.ai.local_cli import LOCAL_CLI_PROVIDERS
from open_notebook.ai.local_cli.detect import detect_all
from open_notebook.ai.models import Model
from open_notebook.exceptions import InvalidInputError

router = APIRouter()


class LocalCLIStatusResponse(BaseModel):
    provider: str
    display_name: str
    installed: bool
    path: Optional[str] = None
    version: Optional[str] = None
    logged_in: Optional[bool] = None
    auth_method: Optional[str] = None
    plan: Optional[str] = None
    error: Optional[str] = None
    suggested_models: List[str] = Field(default_factory=list)
    registered_models: List[dict] = Field(default_factory=list)


class RegisterLocalModelRequest(BaseModel):
    provider: str
    name: str = Field("default", min_length=1, max_length=100)


@router.get("/local-cli/status", response_model=List[LocalCLIStatusResponse])
async def local_cli_status():
    """Detect installed CLIs, versions and login state. Never returns account details."""
    statuses = await asyncio.to_thread(detect_all)
    out = []
    for st in statuses:
        models = await Model.get_all()
        registered = [
            {"id": str(m.id), "name": m.name}
            for m in models
            if m.provider == st.provider and m.type == "language"
        ]
        out.append(LocalCLIStatusResponse(**st.to_dict(), registered_models=registered))
    return out


@router.post("/local-cli/models")
async def register_local_cli_model(request: RegisterLocalModelRequest):
    """Create a language model served by a local CLI (idempotent)."""
    if request.provider not in LOCAL_CLI_PROVIDERS:
        raise InvalidInputError(f"Unknown local CLI provider: {request.provider}")
    name = request.name.strip()
    for m in await Model.get_all():
        if m.provider == request.provider and m.name == name and m.type == "language":
            return {
                "id": str(m.id),
                "name": m.name,
                "provider": m.provider,
                "created": False,
            }
    model = Model(name=name, provider=request.provider, type="language")
    await model.save()
    return {
        "id": str(model.id),
        "name": model.name,
        "provider": model.provider,
        "created": True,
    }
