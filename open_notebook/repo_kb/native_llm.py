"""Bounded, audited model calls without tools or direct repository access."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from open_notebook.ai.local_cli.chat_model import LocalCLIChatModel
from open_notebook.ai.provision import provision_langchain_model
from open_notebook.repo_kb.mask import mask_text
from open_notebook.utils import token_count
from open_notebook.utils.text_utils import extract_text_content


def json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```json\n") and value.endswith("\n```"):
        value = value[8:-4]
    result = json.loads(value)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result


async def invoke(
    system: str,
    prompt: str,
    *,
    model_id: str | None = None,
    timeout: float = 20,
    feature: str = "repo_kb_select",
    model: Any = None,
) -> tuple[str, dict[str, Any]]:
    # Callers may supply only current-policy masked DB material. Mask again
    # for user-provided flow titles/questions/manual notes at the boundary.
    prompt = mask_text(prompt)[0]
    messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
    model = model or await provision_langchain_model(
        prompt, model_id, "chat", max_tokens=8192
    )
    started = time.monotonic()
    config = RunnableConfig(metadata={"audit_feature": feature})
    if isinstance(model, LocalCLIChatModel):
        # Its runner kills and reaps its process group on deadline. Merely
        # cancelling LangChain's default thread-backed ainvoke would orphan it.
        bounded = model.model_copy(update={"timeout": timeout})
        task = asyncio.create_task(
            asyncio.to_thread(bounded.invoke, messages, config=config)
        )
        try:
            answer = await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise
    else:
        answer = await asyncio.wait_for(model.ainvoke(messages, config=config), timeout)
    body = extract_text_content(answer.content)
    usage: dict[str, Any] = getattr(answer, "usage_metadata", None) or {}
    return mask_text(body)[0], {
        "seconds": round(time.monotonic() - started, 3),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "estimated_input_tokens": token_count(prompt),
        "estimated_output_tokens": token_count(body),
    }
