"""LangChain chat model backed by a local AI CLI (Claude Code or Codex)."""

from typing import Any, Dict, Iterator, List, Optional

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.messages.ai import UsageMetadata
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult

from open_notebook.ai.local_cli import CLAUDE_CODE, CODEX_CLI
from open_notebook.ai.local_cli.errors import LocalCLIError, LocalCLIFailure
from open_notebook.ai.local_cli.runners import DEFAULT_TIMEOUT_SECONDS, RUNNERS
from open_notebook.utils.text_utils import extract_text_content

_ROLE = {"human": "User", "ai": "Assistant", "tool": "Tool"}


def messages_to_prompt(messages: List[BaseMessage]) -> tuple[str, str]:
    """Split LangChain messages into (system prompt, user prompt)."""
    system_parts: List[str] = []
    turns: List[BaseMessage] = []
    for m in messages:
        if m.type == "system":
            system_parts.append(extract_text_content(m.content))
        else:
            turns.append(m)
    system = "\n\n".join(p for p in system_parts if p)
    if len(turns) == 1 and turns[0].type == "human":
        return system, extract_text_content(turns[0].content)
    history = "\n\n".join(
        f"{_ROLE.get(m.type, m.type)}: {extract_text_content(m.content)}"
        for m in turns[:-1]
    )
    last = turns[-1] if turns else None
    latest = extract_text_content(last.content) if last else ""
    return system, (
        f"Conversation so far:\n\n{history}\n\nReply to the user's latest message:\n\n{latest}"
        if history
        else latest
    )


def _merge_rate_limit(
    old: Optional[Dict[str, Any]], new: Dict[str, Any]
) -> Dict[str, Any]:
    """Later snapshots may omit windows the CLI already reported; keep them."""
    if old and not new.get("windows") and old.get("windows"):
        return {
            **new,
            "windows": old["windows"],
            "plan": new.get("plan") or old.get("plan"),
        }
    return new


class LocalCLIChatModel(BaseChatModel):
    """Chat model that answers through a locally installed, logged-in AI CLI."""

    provider: str
    model_name: str = "default"
    timeout: float = DEFAULT_TIMEOUT_SECONDS

    @property
    def _llm_type(self) -> str:
        return f"local-cli-{self.provider}"

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        return {"provider": self.provider, "model_name": self.model_name}

    def _stream(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        runner = RUNNERS.get(self.provider)
        if runner is None:
            raise ValueError(f"Unknown local CLI provider: {self.provider}")
        system, prompt = messages_to_prompt(messages)
        audit: Dict[str, Any] = {
            "provider": self.provider,
            "events": [],
            "usage": [],
            "rate_limit": None,
        }
        text_len = 0
        try:
            for ev in runner(system, prompt, self.model_name, self.timeout):
                kind = ev["kind"]
                if kind == "text":
                    text_len += len(ev["text"])
                    chunk = ChatGenerationChunk(
                        message=AIMessageChunk(content=ev["text"])
                    )
                    if run_manager:
                        run_manager.on_llm_new_token(ev["text"], chunk=chunk)
                    yield chunk
                elif kind == "usage":
                    audit["usage"].append(ev)
                elif kind == "rate_limit":
                    audit["rate_limit"] = _merge_rate_limit(
                        audit["rate_limit"], ev["snapshot"]
                    )
                    audit["events"].append(
                        {"type": "status", "name": "rate_limit_snapshot", "detail": {}}
                    )
                elif kind == "status":
                    audit["events"].append(
                        {
                            "type": "status",
                            "name": ev["name"],
                            "detail": ev.get("detail") or {},
                        }
                    )
                elif kind == "done" and text_len == 0 and ev.get("text"):
                    # CLI streamed nothing incrementally; deliver the final text.
                    text_len = len(ev["text"])
                    yield ChatGenerationChunk(
                        message=AIMessageChunk(content=ev["text"])
                    )
            if text_len == 0:
                raise LocalCLIError(LocalCLIFailure.EMPTY_RESPONSE, self._cli_label())
        except LocalCLIError as e:
            audit["events"].append(
                {"type": "error", "name": e.failure.value, "detail": {}}
            )
            typed = e.to_typed()
            setattr(typed, "local_cli_audit", audit)
            setattr(typed, "local_cli_failure", e.failure.value)
            setattr(typed, "local_cli_detail", e.detail)
            raise typed from e
        audit["events"].append({"type": "status", "name": "completed", "detail": {}})
        totals = {
            "input_tokens": sum(u["input_tokens"] for u in audit["usage"]),
            "output_tokens": sum(u["output_tokens"] for u in audit["usage"]),
        }
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                usage_metadata=UsageMetadata(
                    input_tokens=totals["input_tokens"],
                    output_tokens=totals["output_tokens"],
                    total_tokens=totals["input_tokens"] + totals["output_tokens"],
                ),
                response_metadata={"local_cli_audit": audit},
            ),
            generation_info={"local_cli_audit": audit},
        )

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        merged: Optional[ChatGenerationChunk] = None
        for chunk in self._stream(messages, stop, run_manager, **kwargs):
            merged = chunk if merged is None else merged + chunk
        assert merged is not None
        msg = AIMessage(
            content=merged.message.content,
            usage_metadata=getattr(merged.message, "usage_metadata", None),
            response_metadata=merged.message.response_metadata,
        )
        return ChatResult(
            generations=[
                ChatGeneration(message=msg, generation_info=merged.generation_info)
            ]
        )

    def _cli_label(self) -> str:
        return {CLAUDE_CODE: "Claude Code", CODEX_CLI: "Codex"}.get(
            self.provider, self.provider
        )
