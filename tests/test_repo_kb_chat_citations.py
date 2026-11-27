from contextlib import asynccontextmanager

import pytest
from surrealdb import RecordID

from api.routers._chat_shared import ChatMessage
from api.routers.chat import annotate_repo_citations


@pytest.mark.asyncio
async def test_reloaded_replies_recheck_current_citation_permissions(monkeypatch):
    valid = True
    entered = 0

    @asynccontextmanager
    async def connection():
        nonlocal entered
        entered += 1
        yield object()

    async def mounts(_db, _notebook):
        return [{"id": RecordID("repo_kb", "example")}]

    async def resolve(_db, _kb, reference):
        return {"valid": valid and reference == "〔docs:file#L1@abcdef〕"}

    monkeypatch.setattr("open_notebook.database.repository.db_connection", connection)
    monkeypatch.setattr("open_notebook.repo_kb.native_management.mounts", mounts)
    monkeypatch.setattr("open_notebook.repo_kb.native_cite.resolve", resolve)
    ordinary = ChatMessage(id="plain", type="ai", content="Ordinary notebook reply")
    await annotate_repo_citations([ordinary], "notebook:example")
    assert entered == 0
    answer = ChatMessage(
        id="answer",
        type="ai",
        content="Evidence 〔docs:file#L1@abcdef〕 and malformed 〔docs:missing#L1@bad-commit〕",
    )
    await annotate_repo_citations([answer], "notebook:example")
    assert answer.repo_citations == {
        "〔docs:file#L1@abcdef〕": True,
        "〔docs:missing#L1@bad-commit〕": False,
    }
    valid = False
    await annotate_repo_citations([answer], "notebook:example")
    assert not any(answer.repo_citations.values())
