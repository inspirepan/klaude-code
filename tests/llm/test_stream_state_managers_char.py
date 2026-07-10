"""Characterization tests for each provider's StreamStateManager + stream parser.

Each test drives a representative sequence of stream deltas (text, thinking,
tool_call args) through the provider parser and asserts the resulting partial /
final AssistantMessage: ordered parts, their fields, the emitted stream deltas,
usage token counts and stop_reason.

These lock in current observable behavior to protect a future
BaseStreamStateManager extraction. They assert what IS, not what SHOULD be.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from types import SimpleNamespace
from typing import Any, cast

import pytest
from anthropic.types.beta.beta_raw_content_block_delta_event import BetaRawContentBlockDeltaEvent
from anthropic.types.beta.beta_raw_content_block_start_event import BetaRawContentBlockStartEvent
from anthropic.types.beta.beta_raw_content_block_stop_event import BetaRawContentBlockStopEvent
from anthropic.types.beta.beta_raw_message_delta_event import BetaRawMessageDeltaEvent
from anthropic.types.beta.beta_raw_message_start_event import BetaRawMessageStartEvent
from openai import AsyncStream
from openai._models import construct_type_unchecked
from openai.types import responses
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from klaude_code.llm.anthropic.client import (
    AnthropicStreamStateManager,
    parse_anthropic_stream,
)
from klaude_code.llm.bedrock_anthropic.client import parse_bedrock_stream
from klaude_code.llm.google.client import GoogleStreamStateManager, parse_google_stream
from klaude_code.llm.openai_compatible.stream import (
    DefaultReasoningHandler,
    OpenAILLMStream,
)
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message

# --------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------


def _param(*, model_id: str = "test-model", **kwargs: Any) -> llm_param.LLMCallParameter:
    return llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id=model_id,
        session_id="test-session",
        tools=[],
        **kwargs,
    )


def _collect(stream: AsyncIterator[message.LLMStreamItem]) -> list[message.LLMStreamItem]:
    async def _run() -> list[message.LLMStreamItem]:
        return [item async for item in stream]

    return asyncio.run(_run())


def _final(items: list[message.LLMStreamItem]) -> message.AssistantMessage:
    return next(item for item in items if isinstance(item, message.AssistantMessage))


class _ListAsyncIterator:
    def __init__(self, items: Sequence[object]) -> None:
        self._items = list(items)

    def __aiter__(self) -> _ListAsyncIterator:
        return self

    async def __anext__(self) -> object:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------


class _FakeAnthropicStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def __await__(self):
        async def _return_self() -> _FakeAnthropicStream:
            return self

        return _return_self().__await__()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


def _anthropic_events() -> list[object]:
    return [
        BetaRawMessageStartEvent.model_validate(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_anthropic",
                    "type": "message",
                    "role": "assistant",
                    "model": "claude-sonnet-4-6",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {
                        "input_tokens": 100,
                        "output_tokens": 0,
                        "cache_read_input_tokens": 20,
                        "cache_creation_input_tokens": 5,
                    },
                },
            }
        ),
        # Thinking block
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "let me think"},
            }
        ),
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "signature_delta", "signature": "sig-abc"},
            }
        ),
        BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
        # Text block
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "Hello "},
            }
        ),
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 1,
                "delta": {"type": "text_delta", "text": "world"},
            }
        ),
        BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 1}),
        # Tool use block
        BetaRawContentBlockStartEvent.model_validate(
            {
                "type": "content_block_start",
                "index": 2,
                "content_block": {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {}},
            }
        ),
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '{"command":'},
            }
        ),
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 2,
                "delta": {"type": "input_json_delta", "partial_json": '"pwd"}'},
            }
        ),
        BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 2}),
        BetaRawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 42},
            }
        ),
    ]


def test_anthropic_stream_state_manager_full_sequence() -> None:
    param = _param(model_id="claude-sonnet-4-6", context_limit=200000, max_tokens=4096)
    metadata_tracker = MetadataTracker()
    state = AnthropicStreamStateManager(model_id="claude-sonnet-4-6")

    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(_anthropic_events()), param, metadata_tracker, state),
        )
    )
    final = _final(items)

    # Ordered parts: thinking, signature, text, tool call
    assert [type(p) for p in final.parts] == [
        message.ThinkingTextPart,
        message.ThinkingSignaturePart,
        message.TextPart,
        message.ToolCallPart,
    ]
    thinking = final.parts[0]
    sig = final.parts[1]
    text = final.parts[2]
    tool = final.parts[3]
    assert isinstance(thinking, message.ThinkingTextPart)
    assert thinking.text == "let me think"
    assert thinking.model_id == "claude-sonnet-4-6"
    assert isinstance(sig, message.ThinkingSignaturePart)
    assert sig.signature == "sig-abc"
    assert sig.format == "anthropic"
    assert isinstance(text, message.TextPart)
    assert text.text == "Hello world"  # consecutive text deltas merged
    assert isinstance(tool, message.ToolCallPart)
    assert tool.call_id == "toolu_1"
    assert tool.tool_name == "Bash"
    assert tool.arguments_json == '{"command":"pwd"}'

    assert final.stop_reason == "tool_use"
    assert final.response_id == "msg_anthropic"

    # Usage: input_tokens reported as the SUM input + cached + cache_write.
    assert final.usage is not None
    assert final.usage.input_tokens == 100 + 20 + 5
    assert final.usage.cached_tokens == 20
    assert final.usage.cache_write_tokens == 5
    assert final.usage.output_tokens == 42
    assert final.usage.context_size == 125 + 42

    # Emitted deltas in order
    delta_types = [type(i) for i in items if not isinstance(i, message.AssistantMessage)]
    assert delta_types == [
        message.ThinkingTextDelta,
        message.AssistantTextDelta,
        message.AssistantTextDelta,
        message.ToolCallStartDelta,
    ]


# --------------------------------------------------------------------------
# Anthropic deepseek empty-thinking insertion (concern #3)
# --------------------------------------------------------------------------


def _deepseek_tool_only_events() -> list[object]:
    return [
        BetaRawMessageStartEvent.model_validate(
            {
                "type": "message_start",
                "message": {
                    "id": "msg_ds",
                    "type": "message",
                    "role": "assistant",
                    "model": "deepseek-v4-pro",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 0},
                },
            }
        ),
        BetaRawContentBlockStartEvent.model_validate(
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "tool_use", "id": "toolu_ds", "name": "write", "input": {}},
            }
        ),
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "input_json_delta", "partial_json": '{"file_path":"x"}'},
            }
        ),
        BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
        BetaRawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "tool_use", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            }
        ),
    ]


def test_anthropic_deepseek_inserts_empty_thinking_before_tool_call() -> None:
    # deepseek + thinking enabled + tool_use + no thinking part => empty thinking inserted.
    param = _param(model_id="deepseek-v4-pro", thinking=llm_param.Thinking(type="enabled", budget_tokens=1024))
    state = AnthropicStreamStateManager(model_id="deepseek-v4-pro")
    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(_deepseek_tool_only_events()), param, MetadataTracker(), state),
        )
    )
    final = _final(items)
    assert [type(p) for p in final.parts] == [message.ThinkingTextPart, message.ToolCallPart]
    inserted = final.parts[0]
    assert isinstance(inserted, message.ThinkingTextPart)
    assert inserted.text == ""
    assert inserted.model_id == "deepseek-v4-pro"


def test_anthropic_non_deepseek_does_not_insert_empty_thinking() -> None:
    param = _param(model_id="claude-sonnet-4-6", thinking=llm_param.Thinking(type="enabled", budget_tokens=1024))
    state = AnthropicStreamStateManager(model_id="claude-sonnet-4-6")
    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(_deepseek_tool_only_events()), param, MetadataTracker(), state),
        )
    )
    final = _final(items)
    assert [type(p) for p in final.parts] == [message.ToolCallPart]


def test_anthropic_deepseek_no_insert_when_thinking_disabled() -> None:
    param = _param(model_id="deepseek-v4-pro", thinking=llm_param.Thinking(type="disabled"))
    state = AnthropicStreamStateManager(model_id="deepseek-v4-pro")
    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(_deepseek_tool_only_events()), param, MetadataTracker(), state),
        )
    )
    final = _final(items)
    assert [type(p) for p in final.parts] == [message.ToolCallPart]


def test_anthropic_deepseek_no_insert_when_thinking_part_present() -> None:
    # When a thinking part already exists, no empty-thinking is added.
    param = _param(model_id="deepseek-v4-pro", thinking=llm_param.Thinking(type="enabled", budget_tokens=1024))
    state = AnthropicStreamStateManager(model_id="deepseek-v4-pro")
    events = [
        _deepseek_tool_only_events()[0],  # message_start
        BetaRawContentBlockDeltaEvent.model_validate(
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "thinking_delta", "thinking": "real thought"},
            }
        ),
        BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
        *_deepseek_tool_only_events()[1:],
    ]
    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(events), param, MetadataTracker(), state),
        )
    )
    final = _final(items)
    thinking_parts = [p for p in final.parts if isinstance(p, message.ThinkingTextPart)]
    assert len(thinking_parts) == 1
    assert thinking_parts[0].text == "real thought"


def test_anthropic_deepseek_no_insert_when_stop_reason_not_tool_use() -> None:
    param = _param(model_id="deepseek-v4-pro", thinking=llm_param.Thinking(type="enabled", budget_tokens=1024))
    state = AnthropicStreamStateManager(model_id="deepseek-v4-pro")
    # Replace stop_reason with end_turn; still has a tool call but stop != tool_use.
    events = [
        *_deepseek_tool_only_events()[:-1],
        BetaRawMessageDeltaEvent.model_validate(
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 5},
            }
        ),
    ]
    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_anthropic_stream(_FakeAnthropicStream(events), param, MetadataTracker(), state),
        )
    )
    final = _final(items)
    assert [type(p) for p in final.parts] == [message.ToolCallPart]
    assert final.stop_reason == "stop"


# --------------------------------------------------------------------------
# Bedrock (reuses AnthropicStreamStateManager)
# --------------------------------------------------------------------------


class _FakeBedrockSyncStream:
    """Mimics the boto3 EventStream: a plain sync iterator of event dicts."""

    def __init__(self, events: list[dict[str, Any]]) -> None:
        self._events = events

    def __iter__(self):
        return iter(self._events)


def test_bedrock_stream_state_manager_full_sequence() -> None:
    param = _param(model_id="anthropic.claude-sonnet-4-6", context_limit=200000, max_tokens=4096)
    state = AnthropicStreamStateManager(model_id="anthropic.claude-sonnet-4-6")
    response: dict[str, Any] = {
        "ResponseMetadata": {"RequestId": "req-123"},
        "stream": _FakeBedrockSyncStream(
            [
                {"messageStart": {"role": "assistant"}},
                # Reasoning content
                {
                    "contentBlockDelta": {
                        "delta": {"reasoningContent": {"text": "thinking deeply"}},
                        "contentBlockIndex": 0,
                    }
                },
                {
                    "contentBlockDelta": {
                        "delta": {"reasoningContent": {"signature": "bedrock-sig"}},
                        "contentBlockIndex": 0,
                    }
                },
                {"contentBlockStop": {"contentBlockIndex": 0}},
                # Text
                {"contentBlockDelta": {"delta": {"text": "Answer "}, "contentBlockIndex": 1}},
                {"contentBlockDelta": {"delta": {"text": "here"}, "contentBlockIndex": 1}},
                {"contentBlockStop": {"contentBlockIndex": 1}},
                # Tool use
                {
                    "contentBlockStart": {
                        "start": {"toolUse": {"toolUseId": "tu_1", "name": "Bash"}},
                        "contentBlockIndex": 2,
                    }
                },
                {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"command":'}}, "contentBlockIndex": 2}},
                {"contentBlockDelta": {"delta": {"toolUse": {"input": '"ls"}'}}, "contentBlockIndex": 2}},
                {"contentBlockStop": {"contentBlockIndex": 2}},
                {"messageStop": {"stopReason": "tool_use"}},
                {
                    "metadata": {
                        "usage": {
                            "inputTokens": 50,
                            "outputTokens": 12,
                            "cacheReadInputTokens": 8,
                            "cacheWriteInputTokens": 3,
                            "totalTokens": 73,
                        }
                    }
                },
            ]
        ),
    }

    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_bedrock_stream(response, param, MetadataTracker(), state),
        )
    )
    final = _final(items)

    assert [type(p) for p in final.parts] == [
        message.ThinkingTextPart,
        message.ThinkingSignaturePart,
        message.TextPart,
        message.ToolCallPart,
    ]
    thinking = final.parts[0]
    sig = final.parts[1]
    text = final.parts[2]
    tool = final.parts[3]
    assert isinstance(thinking, message.ThinkingTextPart)
    assert thinking.text == "thinking deeply"
    assert isinstance(sig, message.ThinkingSignaturePart)
    assert sig.signature == "bedrock-sig"
    assert sig.format == "anthropic"  # bedrock reuses AnthropicStreamStateManager's format
    assert isinstance(text, message.TextPart)
    assert text.text == "Answer here"
    assert isinstance(tool, message.ToolCallPart)
    assert tool.call_id == "tu_1"
    assert tool.tool_name == "Bash"
    assert tool.arguments_json == '{"command":"ls"}'

    assert final.stop_reason == "tool_use"
    assert final.response_id == "req-123"
    assert final.usage is not None
    assert final.usage.input_tokens == 50
    assert final.usage.output_tokens == 12
    assert final.usage.cached_tokens == 8
    assert final.usage.cache_write_tokens == 3
    assert final.usage.context_size == 73


# --------------------------------------------------------------------------
# Google
# --------------------------------------------------------------------------


def _google_part(
    *,
    text: str | None = None,
    thought: bool | None = None,
    thought_signature: bytes | None = None,
    function_call: object | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        thought=thought,
        thought_signature=thought_signature,
        function_call=function_call,
    )


def _google_chunk(
    *,
    parts: list[object] | None = None,
    finish_reason_name: str | None = None,
    response_id: str | None = None,
    usage_metadata: object | None = None,
    model_version: str | None = None,
) -> SimpleNamespace:
    finish_reason = SimpleNamespace(name=finish_reason_name) if finish_reason_name else None
    content = SimpleNamespace(parts=parts) if parts is not None else None
    candidate = SimpleNamespace(finish_reason=finish_reason, content=content)
    chunk = SimpleNamespace(
        response_id=response_id,
        model_version=model_version,
        usage_metadata=usage_metadata,
        candidates=[candidate],
    )
    # parse_google_stream calls chunk.model_dump for logging.
    chunk.model_dump = lambda **_: {}  # type: ignore[attr-defined]
    return chunk


def test_google_stream_state_manager_full_sequence() -> None:
    param = _param(model_id="gemini-2.5-pro", context_limit=1000000, max_tokens=8192)
    state = GoogleStreamStateManager(param_model="gemini-2.5-pro")

    usage_metadata = SimpleNamespace(
        cached_content_token_count=4,
        prompt_token_count=30,
        candidates_token_count=10,
        thoughts_token_count=6,
        total_token_count=46,
    )
    function_call = SimpleNamespace(
        id="fc_1",
        name="Bash",
        args={"command": "pwd"},
        partial_args=None,
        will_continue=None,
    )
    chunks: list[object] = [
        _google_chunk(
            parts=[_google_part(text="thinking...", thought=True, thought_signature=b"gsig")],
            response_id="resp_google",
        ),
        _google_chunk(parts=[_google_part(text="Final answer", thought=None)]),
        _google_chunk(parts=[_google_part(function_call=function_call)]),
        _google_chunk(finish_reason_name="STOP", usage_metadata=usage_metadata),
    ]

    items = _collect(
        cast(
            AsyncIterator[message.LLMStreamItem],
            parse_google_stream(cast(Any, _ListAsyncIterator(chunks)), param, MetadataTracker(), state),
        )
    )
    final = _final(items)

    assert [type(p) for p in final.parts] == [
        message.ThinkingTextPart,
        message.ThinkingSignaturePart,
        message.TextPart,
        message.ToolCallPart,
    ]
    thinking = final.parts[0]
    sig = final.parts[1]
    text = final.parts[2]
    tool = final.parts[3]
    assert isinstance(thinking, message.ThinkingTextPart)
    assert thinking.text == "thinking..."
    assert thinking.model_id == "gemini-2.5-pro"
    assert isinstance(sig, message.ThinkingSignaturePart)
    # bytes thought_signature is base64-encoded.
    import base64

    assert sig.signature == base64.b64encode(b"gsig").decode("ascii")
    assert sig.format == "google"
    assert isinstance(text, message.TextPart)
    assert text.text == "Final answer"
    assert isinstance(tool, message.ToolCallPart)
    assert tool.call_id == "fc_1"
    assert tool.tool_name == "Bash"
    assert tool.arguments_json == '{"command":"pwd"}'  # canonical JSON, no spaces

    assert final.stop_reason == "stop"
    assert final.response_id == "resp_google"
    assert final.usage is not None
    assert final.usage.input_tokens == 30
    assert final.usage.cached_tokens == 4
    assert final.usage.output_tokens == 10 + 6  # candidates + thoughts
    assert final.usage.reasoning_tokens == 6
    assert final.usage.context_size == 46


# --------------------------------------------------------------------------
# OpenAI-compatible (chat completions)
# --------------------------------------------------------------------------


def test_openai_compatible_stream_state_manager_full_sequence() -> None:
    param = _param(model_id="gpt-4.1-mini")
    tc0_start = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="Bash", arguments=""))
    tc0_args = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='{"command":"pwd"}'))

    events: list[object] = [
        SimpleNamespace(
            id="resp_openai",
            model="gpt-4.1-mini",
            choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content="reasoning here"), finish_reason=None)],
        ),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="Hello "), finish_reason=None)]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="world"), finish_reason=None)]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(tool_calls=[tc0_start]), finish_reason=None)]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(tool_calls=[tc0_args]), finish_reason=None)]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(), finish_reason="tool_calls")]),
    ]

    reasoning_handler = DefaultReasoningHandler(param_model=str(param.model_id), response_id=None)
    stream = OpenAILLMStream(
        cast(AsyncStream[ChatCompletionChunk], _ListAsyncIterator(events)),
        param=param,
        metadata_tracker=MetadataTracker(),
        reasoning_handler=reasoning_handler,
        on_event=None,
    )
    items = _collect(cast(AsyncIterator[message.LLMStreamItem], stream))
    final = _final(items)

    assert [type(p) for p in final.parts] == [
        message.ThinkingTextPart,
        message.TextPart,
        message.ToolCallPart,
    ]
    thinking = final.parts[0]
    text = final.parts[1]
    tool = final.parts[2]
    assert isinstance(thinking, message.ThinkingTextPart)
    assert thinking.text == "reasoning here"
    assert isinstance(text, message.TextPart)
    assert text.text == "Hello world"
    assert isinstance(tool, message.ToolCallPart)
    assert tool.call_id == "call_1"
    assert tool.tool_name == "Bash"
    assert tool.arguments_json == '{"command":"pwd"}'

    assert final.stop_reason == "tool_use"
    assert final.response_id == "resp_openai"

    delta_types = [type(i) for i in items if not isinstance(i, message.AssistantMessage)]
    assert delta_types == [
        message.ThinkingTextDelta,
        message.AssistantTextDelta,
        message.AssistantTextDelta,
        message.ToolCallStartDelta,
    ]


# --------------------------------------------------------------------------
# OpenAI Responses
# --------------------------------------------------------------------------


def _responses_event(value: dict[str, Any]) -> responses.ResponseStreamEvent:
    return cast(
        responses.ResponseStreamEvent,
        construct_type_unchecked(value=value, type_=cast(Any, responses.ResponseStreamEvent)),
    )


def test_responses_stream_state_manager_full_sequence() -> None:
    param = _param(model_id="gpt-5.4")
    events = [
        _responses_event(
            {
                "type": "response.created",
                "sequence_number": 0,
                "response": {"id": "resp_xyz", "created_at": 0, "status": "in_progress", "output": []},
            }
        ),
        _responses_event({"type": "response.reasoning_summary_part.added", "sequence_number": 1}),
        _responses_event(
            {
                "type": "response.reasoning_summary_text.delta",
                "sequence_number": 2,
                "delta": "let me reason",
            }
        ),
        _responses_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "sequence_number": 3,
                "item": {
                    "type": "reasoning",
                    "id": "rs_1",
                    "summary": [],
                    "encrypted_content": "enc-data",
                },
            }
        ),
        _responses_event(
            {
                "type": "response.output_text.delta",
                "sequence_number": 4,
                "delta": "The answer",
            }
        ),
        _responses_event(
            {
                "type": "response.output_item.done",
                "output_index": 1,
                "sequence_number": 5,
                "item": {
                    "type": "function_call",
                    "id": "fc_item",
                    "call_id": "call_99",
                    "name": "Bash",
                    "arguments": ' {"command":"pwd"} ',
                    "status": "completed",
                },
            }
        ),
        _responses_event(
            {
                "type": "response.completed",
                "sequence_number": 6,
                "response": {
                    "id": "resp_xyz",
                    "created_at": 0,
                    "status": "completed",
                    "output": [],
                    "usage": {
                        "input_tokens": 40,
                        "input_tokens_details": {"cached_tokens": 5, "cache_write_tokens": 7},
                        "output_tokens": 20,
                        "output_tokens_details": {"reasoning_tokens": 8},
                        "total_tokens": 60,
                    },
                },
            }
        ),
    ]

    stream = ResponsesLLMStream(
        cast(Any, _ListAsyncIterator(events)),
        param=param,
        metadata_tracker=MetadataTracker(),
    )
    items = _collect(cast(AsyncIterator[message.LLMStreamItem], stream))
    final = _final(items)

    assert [type(p) for p in final.parts] == [
        message.ThinkingTextPart,
        message.ThinkingSignaturePart,
        message.TextPart,
        message.ToolCallPart,
    ]
    thinking = final.parts[0]
    sig = final.parts[1]
    text = final.parts[2]
    tool = final.parts[3]
    assert isinstance(thinking, message.ThinkingTextPart)
    assert thinking.text == "let me reason"
    assert isinstance(sig, message.ThinkingSignaturePart)
    assert sig.signature == "enc-data"
    assert sig.format == "openai-responses"
    assert isinstance(text, message.TextPart)
    assert text.text == "The answer"
    assert isinstance(tool, message.ToolCallPart)
    assert tool.call_id == "call_99"
    assert tool.id == "fc_item"
    assert tool.tool_name == "Bash"
    assert tool.arguments_json == '{"command":"pwd"}'  # arguments stripped

    assert final.stop_reason == "stop"
    assert final.response_id == "resp_xyz"
    assert final.usage is not None
    assert final.usage.input_tokens == 40
    assert final.usage.cached_tokens == 5
    assert final.usage.cache_write_tokens == 7
    assert final.usage.output_tokens == 20
    assert final.usage.reasoning_tokens == 8
    assert final.usage.context_size == 60


@pytest.mark.parametrize(
    ("status", "reason", "expected"),
    [
        ("completed", None, "stop"),
        ("failed", None, "error"),
        ("incomplete", "max_output_tokens", "length"),
        ("incomplete", "content_filter", "error"),
        ("incomplete", "cancelled", "aborted"),
        ("in_progress", None, None),
    ],
)
def test_responses_map_stop_reason_via_stream(status: str, reason: str | None, expected: str | None) -> None:
    """Characterize the nested map_stop_reason closure by driving a completed event."""
    param = _param(model_id="gpt-5.4")
    response: dict[str, Any] = {
        "id": "resp_1",
        "created_at": 0,
        "status": status,
        "output": [],
    }
    if reason is not None:
        response["incomplete_details"] = {"reason": reason}
    events = [
        _responses_event(
            {
                "type": "response.completed",
                "sequence_number": 0,
                "response": response,
            }
        )
    ]
    stream = ResponsesLLMStream(
        cast(Any, _ListAsyncIterator(events)),
        param=param,
        metadata_tracker=MetadataTracker(),
    )
    items = _collect(cast(AsyncIterator[message.LLMStreamItem], stream))
    final = _final(items)
    assert final.stop_reason == expected
