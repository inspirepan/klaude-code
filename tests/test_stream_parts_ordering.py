from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

from openai import AsyncStream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from klaude_code.llm.anthropic.client import AnthropicStreamStateManager
from klaude_code.llm.anthropic.input import convert_history_to_input
from klaude_code.llm.openai_compatible.stream import DefaultReasoningHandler, OpenAILLMStream, StreamStateManager
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


def _basic_call_param(*, model_id: str) -> llm_param.LLMCallParameter:
    return llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id=model_id,
        session_id="test-session",
        tools=[],
    )


def _collect_stream(stream: AsyncIterator[message.LLMStreamItem]) -> list[message.LLMStreamItem]:
    async def _collect() -> list[message.LLMStreamItem]:
        items: list[message.LLMStreamItem] = []
        async for item in stream:
            items.append(item)
        return items

    return asyncio.run(_collect())


class _ListAsyncIterator:
    def __init__(self, items: list[object]) -> None:
        self._items = list(items)

    def __aiter__(self) -> _ListAsyncIterator:
        return self

    async def __anext__(self) -> object:
        if not self._items:
            raise StopAsyncIteration
        return self._items.pop(0)


def test_openai_compatible_parts_preserve_text_reasoning_text_order() -> None:
    param = _basic_call_param(model_id="gpt-4.1-mini")

    # A (assistant text) -> R (reasoning) -> B (assistant text)
    events: list[object] = [
        SimpleNamespace(
            id="r1", model=str(param.model_id), choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]
        ),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(reasoning_content="R"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]),
    ]

    reasoning_handler = DefaultReasoningHandler(param_model=str(param.model_id), response_id=None)
    stream = OpenAILLMStream(
        cast(AsyncStream[ChatCompletionChunk], _ListAsyncIterator(events)),
        param=param,
        metadata_tracker=MetadataTracker(),
        reasoning_handler=reasoning_handler,
        on_event=None,
    )

    items = _collect_stream(cast(AsyncIterator[message.LLMStreamItem], stream))
    final = next(item for item in items if isinstance(item, message.AssistantMessage))

    assert [type(p) for p in final.parts] == [message.TextPart, message.ThinkingTextPart, message.TextPart]
    assert final.parts[0].text == "A"  # type: ignore[attr-defined]
    assert final.parts[1].text == "R"  # type: ignore[attr-defined]
    assert final.parts[2].text == "B"  # type: ignore[attr-defined]


def test_openai_compatible_tool_call_accumulates_args_in_place() -> None:
    param = _basic_call_param(model_id="gpt-4.1-mini")

    tc0_start = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="Bash", arguments=""))
    tc0_args_1 = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='{"com'))
    tc0_args_2 = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name=None, arguments='mand":"pwd"}'))

    events: list[object] = [
        SimpleNamespace(id="r1", choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(tool_calls=[tc0_start]))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(tool_calls=[tc0_args_1]))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(tool_calls=[tc0_args_2]))]),
        SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]),
    ]

    reasoning_handler = DefaultReasoningHandler(param_model=str(param.model_id), response_id=None)
    stream = OpenAILLMStream(
        cast(AsyncStream[ChatCompletionChunk], _ListAsyncIterator(events)),
        param=param,
        metadata_tracker=MetadataTracker(),
        reasoning_handler=reasoning_handler,
        on_event=None,
    )

    items = _collect_stream(cast(AsyncIterator[message.LLMStreamItem], stream))
    final = next(item for item in items if isinstance(item, message.AssistantMessage))

    assert [type(p) for p in final.parts] == [message.TextPart, message.ToolCallPart, message.TextPart]
    tool_part = final.parts[1]
    assert isinstance(tool_part, message.ToolCallPart)
    assert tool_part.call_id == "call_1"
    assert tool_part.tool_name == "Bash"
    assert tool_part.arguments_json == '{"command":"pwd"}'


def test_openai_compatible_partial_message_excludes_tool_calls() -> None:
    state = StreamStateManager(param_model="gpt-4.1-mini")
    state.set_response_id("r1")
    state.append_text("hi")
    state.upsert_tool_call(tc_index=0, call_id="call_1", name="Bash", arguments='{"command":"pwd"}')

    partial = state.get_partial_message()
    assert partial is not None
    assert any(isinstance(p, message.TextPart) for p in partial.parts)
    assert not any(isinstance(p, message.ToolCallPart) for p in partial.parts)


def test_anthropic_state_preserves_thinking_signature_adjacency() -> None:
    state = AnthropicStreamStateManager(model_id="claude-3-5-sonnet")
    state.response_id = "r1"
    state.append_thinking_text("t1")
    state.set_pending_signature("sig1")
    state.flush_pending_signature()
    state.append_text("hello")

    assert [type(p) for p in state.assistant_parts] == [
        message.ThinkingTextPart,
        message.ThinkingSignaturePart,
        message.TextPart,
    ]


def test_anthropic_partial_message_excludes_tool_calls() -> None:
    state = AnthropicStreamStateManager(model_id="claude-3-5-sonnet")
    state.response_id = "r1"
    state.append_text("hi")
    state.current_tool_name = "Bash"
    state.current_tool_call_id = "call_1"
    state.current_tool_inputs = ['{"command":"pwd"}']
    state.flush_tool_call()

    partial = state.get_partial_message()
    assert partial is not None
    assert any(isinstance(p, message.TextPart) for p in partial.parts)
    assert not any(isinstance(p, message.ToolCallPart) for p in partial.parts)


def test_anthropic_input_preserves_degraded_thinking_order_in_place() -> None:
    model = "claude-3-5-sonnet"
    assistant = message.AssistantMessage(
        parts=[
            message.ThinkingTextPart(text="t1", model_id=model),
            message.ThinkingSignaturePart(signature="s1", model_id=model, format="anthropic"),
            message.TextPart(text="hello"),
            message.ThinkingTextPart(text="other", model_id="other-model"),
            message.TextPart(text="world"),
        ]
    )

    out = convert_history_to_input([assistant], model_name=model)
    assert len(out) == 1
    msg0 = out[0]
    assert msg0["role"] == "assistant"
    blocks: list[dict[str, Any]] = list(msg0["content"])  # type: ignore[arg-type]
    assert [b.get("type") for b in blocks] == ["thinking", "text", "text", "text"]
    assert blocks[0]["thinking"] == "t1"
    assert blocks[0]["signature"] == "s1"
    assert blocks[1]["text"] == "hello"
    assert "<thinking>" in blocks[2]["text"]
    assert "other" in blocks[2]["text"]
    assert blocks[3]["text"] == "world"
