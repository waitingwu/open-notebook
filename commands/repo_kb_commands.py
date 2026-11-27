"""Repository KB background jobs, executed by the existing worker."""

from typing import Any

from surreal_commands import CommandInput, CommandOutput, command

from open_notebook.database.repository import db_connection
from open_notebook.repo_kb.native_db import record
from open_notebook.repo_kb.native_jobs import execute_job


class RepoKBJobInput(CommandInput):
    job_id: str


class RepoKBJobOutput(CommandOutput):
    result: dict[str, Any]


@command("repo_kb_job", app="open_notebook", retry={"max_attempts": 1})
async def repo_kb_job(input_data: RepoKBJobInput) -> RepoKBJobOutput:
    async with db_connection() as db:
        result = await execute_job(db, record(input_data.job_id, "repo_kb_job"))
    return RepoKBJobOutput(result=result)


class RepoKBBatchInput(CommandInput):
    batch_id: str


@command("repo_kb_batch", app="open_notebook", retry={"max_attempts": 1})
async def repo_kb_batch(input_data: RepoKBBatchInput) -> RepoKBJobOutput:
    from open_notebook.repo_kb.native_batches import execute_batch

    async with db_connection() as db:
        result = await execute_batch(db, record(input_data.batch_id, "repo_kb_batch"))
    return RepoKBJobOutput(result=result)
