from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from klaude_code.agent.task import SessionContext
from klaude_code.agent.turn import TurnError, TurnExecutionContext, TurnExecutor
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message
from klaude_code.tool.core.runner import ToolCallRequest, ToolExecutionResult


class ErrorWithPartialTextStream(LLMStreamABC):
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        # Simulate partial text received before stream error (matches real client behavior)
        yield message.AssistantTextDelta(content="partial answer", response_id="r1")
        yield message.StreamErrorItem(error="network interrupted")
        yield message.AssistantMessage(
            parts=[message.TextPart(text="partial answer")],
            response_id="r1",
            stop_reason="error",
        )

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class InterruptWithPartialTextStream(LLMStreamABC):
    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        if False:
            yield message.StreamErrorItem(error="unreachable")

    def get_partial_message(self) -> message.AssistantMessage | None:
        return message.AssistantMessage(
            parts=[message.TextPart(text="partial answer")],
            response_id="r1",
            stop_reason="aborted",
        )


class FakeLLMClient(LLMClientABC):
    def __init__(
        self,
        stream: LLMStreamABC,
        *,
        protocol: llm_param.LLMClientProtocol = llm_param.LLMClientProtocol.ANTHROPIC,
    ) -> None:
        super().__init__(
            llm_param.LLMConfigParameter(
                provider_name="test",
                protocol=protocol,
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


def _build_turn_executor(
    stream: LLMStreamABC,
    *,
    protocol: llm_param.LLMClientProtocol = llm_param.LLMClientProtocol.ANTHROPIC,
) -> tuple[TurnExecutor, list[message.HistoryEvent]]:
    history: list[message.HistoryEvent] = []

    def append_history(items: Sequence[message.HistoryEvent]) -> None:
        history.extend(items)

    session_ctx = SessionContext(
        session_id="session-test",
        work_dir=Path("/tmp"),
        get_conversation_history=lambda: history,
        append_history=append_history,
        file_tracker=cast(Any, SimpleNamespace()),
        file_change_summary=cast(Any, SimpleNamespace()),
        todo_context=cast(Any, SimpleNamespace()),
        run_subtask=None,
        request_user_interaction=None,
    )
    context = TurnExecutionContext(
        session_ctx=session_ctx,
        llm_client=FakeLLMClient(stream, protocol=protocol),
        system_prompt=None,
        tools=[],
        tool_registry={},
    )
    return TurnExecutor(context), history


def test_stream_error_retries_with_user_continuation_prompt_for_all_protocols() -> None:
    executor, history = _build_turn_executor(
        ErrorWithPartialTextStream(),
        protocol=llm_param.LLMClientProtocol.OPENAI,
    )

    async def _run() -> None:
        with pytest.raises(TurnError, match="network interrupted"):
            async for _ in executor.run():
                pass

    asyncio.run(_run())

    assert any(isinstance(item, message.StreamErrorItem) for item in history)
    assert not any(isinstance(item, message.AssistantMessage) for item in history)

    retry_user_messages = [item for item in history if isinstance(item, message.UserMessage)]
    assert len(retry_user_messages) == 1
    retry_prompt = message.join_text_parts(retry_user_messages[0].parts)
    assert "<assistant>" in retry_prompt
    assert "</assistant>" in retry_prompt
    assert "partial answer" in retry_prompt
    assert "<system-reminder>" in retry_prompt
    assert "</system-reminder>" in retry_prompt
    assert "transient error" in retry_prompt
    assert "network-related" in retry_prompt
    assert "without repeating" in retry_prompt


def test_interrupt_persists_user_continuation_prompt_instead_of_aborted_assistant() -> None:
    stream = InterruptWithPartialTextStream()
    executor, history = _build_turn_executor(stream)
    executor._llm_stream = stream  # pyright: ignore[reportPrivateUsage]
    # Simulate text that would have been accumulated from AssistantTextDelta events
    executor._accumulated_assistant_text = ["partial answer"]  # pyright: ignore[reportPrivateUsage]
    executor._visible_output_started = True  # pyright: ignore[reportPrivateUsage]

    _ = executor.on_interrupt()

    retry_user_messages = [item for item in history if isinstance(item, message.UserMessage)]
    assert len(retry_user_messages) == 1
    retry_prompt = message.join_text_parts(retry_user_messages[0].parts)
    assert "<assistant>" in retry_prompt
    assert "</assistant>" in retry_prompt
    assert "partial answer" in retry_prompt
    assert "<system-reminder>" in retry_prompt
    assert "</system-reminder>" in retry_prompt

    assert not any(isinstance(item, message.AssistantMessage) and item.stop_reason == "aborted" for item in history)
    assert executor.should_show_interrupt_notice is True


def test_interrupt_with_only_thinking_does_not_persist_continuation_prompt() -> None:
    """When only thinking content was produced, no continuation prompt should be generated."""
    stream = InterruptWithPartialTextStream()
    executor, history = _build_turn_executor(stream)
    executor._llm_stream = stream  # pyright: ignore[reportPrivateUsage]
    # No assistant text accumulated - only thinking was produced

    _ = executor.on_interrupt()

    retry_user_messages = [item for item in history if isinstance(item, message.UserMessage)]
    assert len(retry_user_messages) == 0
    assert executor.should_show_interrupt_notice is False


def test_interrupt_writes_tool_result_before_continuation_prompt() -> None:
    stream = InterruptWithPartialTextStream()
    executor, history = _build_turn_executor(stream)
    tool_call_id = "toolu_123"
    history.append(
        message.AssistantMessage(
            parts=[
                message.TextPart(text="验证编译是否通过："),
                message.ToolCallPart(
                    call_id=tool_call_id,
                    tool_name="Bash",
                    arguments_json='{"command":"go build ./..."}',
                ),
            ],
            response_id="r1",
            stop_reason="tool_use",
        )
    )
    executor._accumulated_assistant_text = ["验证编译是否通过："]  # pyright: ignore[reportPrivateUsage]

    class _StubToolExecutor:
        def on_interrupt(self) -> list[ToolExecutionResult]:
            tool_call = ToolCallRequest(
                response_id="r1",
                call_id=tool_call_id,
                tool_name="Bash",
                arguments_json='{"command":"go build ./..."}',
            )
            tool_result = message.ToolResultMessage(
                call_id=tool_call_id,
                tool_name="Bash",
                output_text="[Request interrupted by user for tool use]",
                status="aborted",
            )
            history.append(tool_result)
            return [ToolExecutionResult(tool_call=tool_call, tool_result=tool_result, is_last_in_turn=True)]

    executor._tool_executor = cast(Any, _StubToolExecutor())  # pyright: ignore[reportPrivateUsage]

    _ = executor.on_interrupt()

    assert isinstance(history[0], message.AssistantMessage)
    assert isinstance(history[1], message.ToolResultMessage)
    retry_user_message = history[2]
    assert isinstance(retry_user_message, message.UserMessage)

    retry_prompt = message.join_text_parts(retry_user_message.parts)
    assert "<assistant>" in retry_prompt
    assert "</assistant>" in retry_prompt
