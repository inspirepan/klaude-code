from __future__ import annotations

from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import klaude_code.agent.task as task_module
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import events, llm_param, message
from klaude_code.session.session import Session
from klaude_code.tool.core.abc import ToolABC
from klaude_code.tool.core.context import build_todo_context


class ScriptedLLMStream(LLMStreamABC):
    """LLM stream that yields pre-scripted items."""

    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = items
        self._partial_parts: list[message.Part] = []
        self._response_id: str | None = None
        self._final_message: message.AssistantMessage | None = None

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            if isinstance(item, message.ThinkingTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.ThinkingTextPart(text=item.content))
            elif isinstance(item, message.AssistantTextDelta):
                self._response_id = item.response_id
                self._partial_parts.append(message.TextPart(text=item.content))
            elif isinstance(item, message.AssistantMessage):
                self._final_message = item
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._final_message is not None:
            return self._final_message
        if not self._partial_parts:
            return None
        return message.AssistantMessage(
            parts=list(self._partial_parts),
            response_id=self._response_id,
            stop_reason="aborted",
        )


class FakeLLMClient(LLMClientABC):
    """Fake LLM client with a queue of scripted responses."""

    def __init__(self) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                model_id="fake-model",
            )
        )
        self._responses: list[
            list[message.LLMStreamItem] | Callable[[llm_param.LLMCallParameter], list[message.LLMStreamItem]]
        ] = []

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        return cls()

    def enqueue(self, *items: message.LLMStreamItem) -> None:
        self._responses.append(list(items))

    def enqueue_factory(self, fn: Callable[[llm_param.LLMCallParameter], list[message.LLMStreamItem]]) -> None:
        self._responses.append(fn)

    @property
    def pending_count(self) -> int:
        return len(self._responses)

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        if not self._responses:
            raise RuntimeError("FakeLLMClient has no queued response")
        entry = self._responses.pop(0)
        items = entry(param) if callable(entry) else entry
        return ScriptedLLMStream(items)


@dataclass
class Harness:
    """Test harness for TaskExecutor integration tests."""

    session: Session
    session_ctx: SessionContext
    fake_llm: FakeLLMClient
    tool_registry: dict[str, type[ToolABC]]
    _monkeypatch: Any = field(repr=False)

    async def run_task(self, text: str = "hello") -> list[events.Event]:
        """Run a full task and collect all events."""
        # Append user message to session history before running
        self.session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str(text)),
            ]
        )

        tool_schemas = [tool_cls.schema() for tool_cls in self.tool_registry.values()]
        profile = AgentProfile(
            llm_client=self.fake_llm,
            system_prompt="You are a test assistant.",
            tools=tool_schemas,
            attachments=[],
        )

        ctx = TaskExecutionContext(
            session=self.session,
            session_ctx=self.session_ctx,
            profile=profile,
            tool_registry=self.tool_registry,
            sub_agent_state=None,
        )
        executor = TaskExecutor(ctx)
        collected: list[events.Event] = []
        async for event in executor.run(message.UserInputPayload(text=text)):
            collected.append(event)
        return collected

    def get_history_messages(self) -> list[message.HistoryEvent]:
        return list(self.session.conversation_history)

    def get_assistant_texts(self) -> list[str]:
        texts: list[str] = []
        for item in self.session.conversation_history:
            if isinstance(item, message.AssistantMessage):
                text = message.join_text_parts(item.parts)
                if text:
                    texts.append(text)
        return texts

    def get_user_texts(self) -> list[str]:
        texts: list[str] = []
        for item in self.session.conversation_history:
            if isinstance(item, message.UserMessage):
                text = message.join_text_parts(item.parts)
                if text:
                    texts.append(text)
        return texts


async def create_harness(
    *,
    work_dir: Path,
    tools: dict[str, type[ToolABC]] | None = None,
    system_prompt: str | None = "You are a test assistant.",
    monkeypatch: Any,
) -> Harness:
    """Create a test harness with all dependencies wired up."""

    def _never_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
        del session, config, llm_config
        return False

    monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)

    session = Session.create(work_dir=work_dir)
    tool_registry = tools or {}

    session_ctx = SessionContext(
        session_id=session.id,
        work_dir=work_dir,
        get_conversation_history=session.get_llm_history,
        append_history=session.append_history,
        file_tracker=session.file_tracker,
        file_change_summary=session.file_change_summary,
        todo_context=build_todo_context(session),
        run_subtask=None,
        request_user_interaction=None,
    )

    fake_llm = FakeLLMClient()

    return Harness(
        session=session,
        session_ctx=session_ctx,
        fake_llm=fake_llm,
        tool_registry=tool_registry,
        _monkeypatch=monkeypatch,
    )
