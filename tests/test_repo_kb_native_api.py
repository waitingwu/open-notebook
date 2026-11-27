import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from surrealdb import AsyncSurreal

from api.routers.repo_kb import database, router
from open_notebook.database.async_migrate import AsyncMigrationManager
from open_notebook.exceptions import ConflictError, OpenNotebookError
from open_notebook.repo_kb.native_db import record
from open_notebook.repo_kb.native_jobs import execute_job


@pytest.mark.asyncio
async def test_api_first_sync_confirmation_queue_lock_progress_and_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (
        ("init", "-q"),
        ("config", "user.name", "Test"),
        ("config", "user.email", "test@example.invalid"),
    ):
        subprocess.run(["git", "-C", str(repo), *args], check=True)
    (repo / "操作手冊.txt").write_text("執行紀錄位置\npassword: hidden-value\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True)
    monkeypatch.setattr(
        "surreal_commands.submit_command", lambda *_args: "command:test"
    )
    db: Any
    async with AsyncSurreal("mem://") as db:
        await db.use("repo_kb_api", "flow")
        await db.query("DEFINE TABLE notebook SCHEMAFULL;")
        await db.query(AsyncMigrationManager().up_migrations[29].sql)
        await db.query(AsyncMigrationManager().up_migrations[30].sql)
        app = FastAPI()
        app.include_router(router, prefix="/api")

        async def get_db():
            yield db

        app.dependency_overrides[database] = get_db

        @app.exception_handler(OpenNotebookError)
        async def domain_error(_request, exc):
            return JSONResponse(
                status_code=409 if isinstance(exc, ConflictError) else 400,
                content={"detail": str(exc)},
            )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            kb = (
                await client.post("/api/repo-kb/kbs", json={"name": "Example"})
            ).json()
            response = await client.post(
                f"/api/repo-kb/kbs/{kb['id']}/sources",
                json={
                    "name": "docs",
                    "path": str(repo),
                    "role": "doc",
                    "protected": [],
                },
            )
            assert response.status_code == 200, response.text
            source = response.json()
            assert source["protected"] == []
            response = await client.post(f"/api/repo-kb/sources/{source['id']}/preview")
            assert response.json()["files"] == 1
            response = await client.post(
                f"/api/repo-kb/sources/{source['id']}/sync", json={"mode": "auto"}
            )
            assert response.status_code == 409
            response = await client.post(
                f"/api/repo-kb/sources/{source['id']}/sync",
                json={"confirmed": True, "config_hash": source["config_hash"]},
            )
            assert response.status_code == 200, response.text
            submitted = response.json()
            response = await client.post(
                f"/api/repo-kb/sources/{source['id']}/sync",
                json={"confirmed": True, "config_hash": source["config_hash"]},
            )
            assert response.status_code == 409
            result = await execute_job(db, record(submitted["job_id"], "repo_kb_job"))
            assert result[source["id"]]["files"] == 1
            job = (await client.get(f"/api/repo-kb/jobs/{submitted['job_id']}")).json()
            assert job["status"] == "completed"
            assert job["progress"]["stage"] == "done"
            assert "lock_token" not in job
            assert "hidden-value" not in str(job)
