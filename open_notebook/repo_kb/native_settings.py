"""Shared settings and filesystem boundaries for API and worker."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from open_notebook.repo_kb.native_db import query


async def settings(db: Any) -> dict[str, Any]:
    row = await query(db, "SELECT * FROM ONLY open_notebook:repo_kb_settings;")
    return {
        "default_protected": [],
        "allowed_roots": [],
        "selector_timeout": 20,
        **(row if isinstance(row, dict) else {}),
    }


async def allowed_roots(db: Any) -> list[str]:
    configured = os.environ.get("REPO_KB_ALLOWED_ROOTS", "")
    return (
        configured.split(os.pathsep)
        if configured
        else (await settings(db)).get("allowed_roots", [])
    )


def data_roots() -> list[str]:
    from open_notebook.config import (
        DATA_FOLDER,
        LANGGRAPH_CHECKPOINT_FILE,
        UPLOADS_FOLDER,
    )

    roots = [
        DATA_FOLDER,
        UPLOADS_FOLDER,
        str(Path(LANGGRAPH_CHECKPOINT_FILE).parent),
        "./data",
        "./surreal_data",
        "./surreal-data",
        "/mydata",
    ]
    roots.extend(
        value
        for value in os.environ.get("REPO_KB_DATA_ROOTS", "").split(os.pathsep)
        if value
    )
    return list(
        dict.fromkeys(str(Path(value).expanduser().resolve()) for value in roots)
    )
