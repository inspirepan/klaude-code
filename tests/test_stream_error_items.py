from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any, cast

import httpx

from klaude_code.llm.anthropic.client import AnthropicLLMStream
from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler, OpenAILLMStream
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


class _AwaitableOf:
    def __init__(self, iterator: AsyncIterator[object]) -> None:
        self._iterator = iterator

    def __await__(self):
        async def _coro() -> AsyncIterator[object]:
            return self._iterator

        return _coro().__await__()


class _RemoteProtocolErrorAsyncIterator:
    def __aiter__(self) -> _RemoteProtocolErrorAsyncIterator:
        return self

    async def __anext__(self) -> object:
        raise httpx.RemoteProtocolError(
            "peer closed connection without sending complete message body (incomplete chunked read)",
            request=None,
        )


class _AwaitRaisesRemoteProtocolError:
    def __await__(self):
        async def _coro() -> AsyncIterator[object]:
            raise httpx.RemoteProtocolError(
                "peer closed connection without sending complete message body (incomplete chunked read)",
                request=None,
            )

        return _coro().__await__()


def _basic_call_param(*, model_id: str) -> llm_param.LLMCallParameter:
    return llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id=model_id,
        session_id="test-session",
        tools=[],
    )


def _collect_stream(stream: object) -> list[message.LLMStreamItem]:
    async def _collect() -> list[message.LLMStreamItem]:
        items: list[message.LLMStreamItem] = []
        iterator = cast(AsyncIterator[message.LLMStreamItem], stream)
        async for item in iterator:
            items.append(item)
        return items

    return asyncio.run(_collect())


def test_anthropic_stream_remote_protocol_error_becomes_stream_error_item() -> None:
    param = _basic_call_param(model_id="claude-3-5-sonnet")
    stream = AnthropicLLMStream(
        _AwaitableOf(_RemoteProtocolErrorAsyncIterator()),
        param=param,
        metadata_tracker=MetadataTracker(),
    )

    items = _collect_stream(stream)
    assert any(isinstance(item, message.StreamErrorItem) for item in items)
    assert any(isinstance(item, message.AssistantMessage) for item in items)


def test_anthropic_stream_error_while_awaiting_stream_is_captured() -> None:
    param = _basic_call_param(model_id="claude-3-5-sonnet")
    stream = AnthropicLLMStream(
        _AwaitRaisesRemoteProtocolError(),
        param=param,
        metadata_tracker=MetadataTracker(),
    )

    items = _collect_stream(stream)
    error_items = [item for item in items if isinstance(item, message.StreamErrorItem)]
    assert error_items
    assert "RemoteProtocolError" in error_items[0].error


def test_openai_compatible_stream_remote_protocol_error_becomes_stream_error_item() -> None:
    param = _basic_call_param(model_id="gpt-4.1-mini")
    reasoning_handler = DefaultReasoningHandler(param_model=str(param.model_id), response_id=None)
    stream = OpenAILLMStream(
        cast(Any, _RemoteProtocolErrorAsyncIterator()),
        param=param,
        metadata_tracker=MetadataTracker(),
        reasoning_handler=reasoning_handler,
        on_event=None,
    )

    items = _collect_stream(stream)
    assert any(isinstance(item, message.StreamErrorItem) for item in items)
    assert any(isinstance(item, message.AssistantMessage) for item in items)


def test_responses_stream_remote_protocol_error_becomes_stream_error_item() -> None:
    param = _basic_call_param(model_id="gpt-4.1-mini")
    stream = ResponsesLLMStream(
        cast(Any, _RemoteProtocolErrorAsyncIterator()),
        param=param,
        metadata_tracker=MetadataTracker(),
    )

    items = _collect_stream(stream)
    assert any(isinstance(item, message.StreamErrorItem) for item in items)
    assert any(isinstance(item, message.AssistantMessage) for item in items)
