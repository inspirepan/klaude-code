from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest

import klaude_code.core.turn as turn_module
from klaude_code.core.task import SessionContext
from klaude_code.core.turn import TurnError, TurnExecutionContext, TurnExecutor
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import events, llm_param, message


class NeverRespondingStream(LLMStreamABC):
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        await asyncio.sleep(3600)
        if False:
            yield message.StreamErrorItem(error="unreachable")

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class FirstTokenThenDelayedCompletionStream(LLMStreamABC):
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        yield message.AssistantTextDelta(content="ok", response_id="r1")
        await asyncio.sleep(0.02)
        yield message.AssistantMessage(
            parts=[message.TextPart(text="ok")],
            response_id="r1",
            stop_reason="stop",
        )

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class FakeLLMClient(LLMClientABC):
    def __init__(self, stream: LLMStreamABC) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=llm_param.LLMClientProtocol.ANTHROPIC,
                model_id="claude-sonnet-test",
            )
        )
        self._stream = stream

    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        del config
        raise NotImplementedError

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        return self._stream


def _build_turn_executor(stream: LLMStreamABC) -> tuple[TurnExecutor, list[message.HistoryEvent]]:
    history: list[message.HistoryEvent] = []

    def append_history(items: Sequence[message.HistoryEvent]) -> None:
        history.extend(items)

    session_ctx = SessionContext(
        session_id="session-test",
        get_conversation_history=lambda: history,
        append_history=append_history,
        file_tracker=cast(Any, SimpleNamespace()),
        todo_context=cast(Any, SimpleNamespace()),
        run_subtask=None,
        request_user_interaction=None,
    )
    context = TurnExecutionContext(
        session_ctx=session_ctx,
        llm_client=FakeLLMClient(stream),
        system_prompt=None,
        tools=[],
        tool_registry={},
    )
    return TurnExecutor(context), history


def test_retry_when_no_first_token_within_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_module, "LLM_FIRST_TOKEN_TIMEOUT_S", 0.01)
    executor, history = _build_turn_executor(NeverRespondingStream())

    async def _run() -> list[events.Event]:
        emitted: list[events.Event] = []
        with pytest.raises(TurnError, match="First token timeout"):
            async for event in executor.run():
                emitted.append(event)
        return emitted

    emitted = asyncio.run(_run())
    assert any(isinstance(event, events.TurnStartEvent) for event in emitted)
    assert any(isinstance(event, events.TurnEndEvent) for event in emitted)
    assert any(isinstance(item, message.StreamErrorItem) for item in history)


def test_first_token_timeout_applies_only_before_stream_start(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(turn_module, "LLM_FIRST_TOKEN_TIMEOUT_S", 0.01)
    executor, _ = _build_turn_executor(FirstTokenThenDelayedCompletionStream())

    async def _run() -> list[events.Event]:
        emitted: list[events.Event] = []
        async for event in executor.run():
            emitted.append(event)
        return emitted

    emitted = asyncio.run(_run())
    assert any(isinstance(event, events.ResponseCompleteEvent) for event in emitted)
    assert executor.task_result == "ok"
