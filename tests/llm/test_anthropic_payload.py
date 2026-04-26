import asyncio
from typing import Any, cast

from anthropic.types.beta.beta_raw_content_block_start_event import BetaRawContentBlockStartEvent
from anthropic.types.beta.beta_raw_content_block_stop_event import BetaRawContentBlockStopEvent
from anthropic.types.beta.beta_raw_message_delta_event import BetaRawMessageDeltaEvent
from anthropic.types.beta.beta_raw_message_start_event import BetaRawMessageStartEvent

from klaude_code.const import ANTHROPIC_BETA_CONTEXT_MANAGEMENT, ANTHROPIC_BETA_INTERLEAVED_THINKING
from klaude_code.llm.anthropic.client import (
    AnthropicStreamStateManager,
    build_payload,
    parse_anthropic_stream,
)
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


def _dummy_history() -> list[message.Message]:
    return [message.UserMessage(parts=[message.TextPart(text="hi")])]


def _dummy_tools() -> list[llm_param.ToolSchema]:
    return [
        llm_param.ToolSchema(
            name="write",
            type="function",
            description="Write a file",
            parameters={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["file_path", "content"],
                "additionalProperties": False,
            },
        )
    ]


class _FakeAnthropicStream:
    def __init__(self, events: list[object]) -> None:
        self._events = events

    def __await__(self):
        async def _return_self() -> "_FakeAnthropicStream":
            return self

        return _return_self().__await__()

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        for event in self._events:
            yield event


def test_build_payload_omits_interleaved_beta_for_adaptive_sonnet_46() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    # Adaptive thinking has interleaved-thinking built in; no beta header needed
    assert ANTHROPIC_BETA_INTERLEAVED_THINKING not in payload.get("betas", [])


def test_build_payload_adds_context_management_beta_when_thinking_enabled() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-7",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert ANTHROPIC_BETA_CONTEXT_MANAGEMENT in payload.get("betas", [])
    assert payload.get("context_management") == {
        "edits": [{"type": "clear_thinking_20251015", "keep": "all"}],
    }


def test_build_payload_skips_context_management_without_thinking() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
    )

    payload = build_payload(param)

    assert "context_management" not in payload
    assert ANTHROPIC_BETA_CONTEXT_MANAGEMENT not in payload.get("betas", [])


def test_build_payload_omits_temperature_for_opus_47() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-7",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert "temperature" not in payload


def test_build_payload_includes_temperature_for_opus_46() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-6",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert "temperature" in payload


def test_build_payload_sets_thinking_display_summarized_for_opus_47() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-7",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    thinking = payload.get("thinking")
    assert thinking is not None
    assert thinking["type"] == "adaptive"  # type: ignore[index]
    assert thinking["display"] == "summarized"  # type: ignore[index]


def test_build_payload_no_thinking_display_for_opus_46() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-6",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    thinking = payload.get("thinking")
    assert thinking is not None
    assert "display" not in thinking  # type: ignore[operator]


def test_build_payload_includes_interleaved_beta_when_needed() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-3-7-sonnet-20250219",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    assert ANTHROPIC_BETA_INTERLEAVED_THINKING in payload.get("betas", [])


def test_build_payload_sets_explicit_disabled_thinking() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        thinking=llm_param.Thinking(type="disabled"),
    )

    payload = build_payload(param)

    assert payload.get("thinking") == {"type": "disabled"}
    assert "context_management" not in payload


def test_build_payload_enables_eager_input_streaming_for_claude_tools() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        tools=_dummy_tools(),
    )

    payload = build_payload(param)

    tools = list(payload.get("tools", []))
    assert "type" not in tools[0]
    assert tools[0]["eager_input_streaming"] is True  # type: ignore[typeddict-item]


def test_build_payload_does_not_enable_eager_input_streaming_for_opus_47() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-opus-4-7",
        tools=_dummy_tools(),
    )

    payload = build_payload(param)

    tools = list(payload.get("tools", []))
    assert "eager_input_streaming" not in tools[0]


def test_build_payload_does_not_enable_eager_input_streaming_for_non_claude_models() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="deepseek-v4-flash",
        tools=_dummy_tools(),
    )

    payload = build_payload(param)

    tools = list(payload.get("tools", []))
    assert "eager_input_streaming" not in tools[0]


def test_build_payload_preserves_empty_deepseek_thinking_before_tool_use() -> None:
    param = llm_param.LLMCallParameter(
        input=[
            message.UserMessage(parts=[message.TextPart(text="call tool")]),
            message.AssistantMessage(
                parts=[
                    message.ThinkingTextPart(text="", model_id="deepseek-v4-pro"),
                    message.ToolCallPart(call_id="toolu_test", tool_name="write", arguments_json='{"file_path":"x"}'),
                ]
            ),
            message.ToolResultMessage(
                call_id="toolu_test",
                tool_name="write",
                status="success",
                output_text="ok",
            ),
        ],
        model_id="deepseek-v4-pro",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    payload_messages = list(payload["messages"])
    assistant_content = payload_messages[1]["content"]
    assert not isinstance(assistant_content, str)
    blocks = [cast(dict[str, Any], block) for block in assistant_content]
    assert blocks[0] == {"type": "thinking", "thinking": ""}
    assert blocks[1]["type"] == "tool_use"


def test_build_payload_adds_empty_deepseek_thinking_for_legacy_tool_use_without_thinking() -> None:
    param = llm_param.LLMCallParameter(
        input=[
            message.UserMessage(parts=[message.TextPart(text="call tool")]),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="toolu_test", tool_name="write", arguments_json='{"file_path":"x"}')
                ],
                stop_reason="tool_use",
            ),
            message.ToolResultMessage(
                call_id="toolu_test",
                tool_name="write",
                status="success",
                output_text="ok",
            ),
        ],
        model_id="deepseek-v4-pro",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    payload_messages = list(payload["messages"])
    assistant_content = payload_messages[1]["content"]
    assert not isinstance(assistant_content, str)
    blocks = [cast(dict[str, Any], block) for block in assistant_content]
    assert blocks[0] == {"type": "thinking", "thinking": ""}
    assert blocks[1]["type"] == "tool_use"


def test_build_payload_adds_empty_deepseek_thinking_for_cross_model_tool_use() -> None:
    param = llm_param.LLMCallParameter(
        input=[
            message.UserMessage(parts=[message.TextPart(text="call tool")]),
            message.AssistantMessage(
                parts=[
                    message.ThinkingTextPart(text="gpt thought", model_id="gpt-5.5"),
                    message.ThinkingSignaturePart(signature="gpt-sig", model_id="gpt-5.5", format="openai"),
                    message.ToolCallPart(call_id="toolu_test", tool_name="write", arguments_json='{"file_path":"x"}'),
                ],
                stop_reason="stop",
            ),
            message.ToolResultMessage(
                call_id="toolu_test",
                tool_name="write",
                status="success",
                output_text="ok",
            ),
        ],
        model_id="deepseek-v4-pro",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    payload_messages = list(payload["messages"])
    assistant_content = payload_messages[1]["content"]
    assert not isinstance(assistant_content, str)
    blocks = [cast(dict[str, Any], block) for block in assistant_content]
    assert blocks[0]["type"] == "text"
    assert "gpt thought" in blocks[0]["text"]
    assert blocks[1] == {"type": "thinking", "thinking": ""}
    assert blocks[2]["type"] == "tool_use"


def test_parse_anthropic_stream_reads_stop_reason_from_nested_delta() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        context_limit=1000,
        max_tokens=256,
    )
    stream = _FakeAnthropicStream(
        [
            BetaRawMessageStartEvent.model_validate(
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": "claude-sonnet-4-6",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                }
            ),
            BetaRawMessageDeltaEvent.model_validate(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 5},
                }
            ),
        ]
    )

    async def _collect() -> list[message.LLMStreamItem]:
        items: list[message.LLMStreamItem] = []
        async for item in parse_anthropic_stream(
            stream,
            param,
            MetadataTracker(),
            AnthropicStreamStateManager(model_id=str(param.model_id)),
        ):
            items.append(item)
        return items

    items = asyncio.run(_collect())

    assert isinstance(items[-1], message.AssistantMessage)
    assert items[-1].stop_reason == "tool_use"


def test_parse_anthropic_stream_adds_deepseek_empty_thinking_for_tool_use_without_thinking() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="deepseek-v4-pro",
        context_limit=1000,
        max_tokens=256,
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )
    stream = _FakeAnthropicStream(
        [
            BetaRawMessageStartEvent.model_validate(
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "content": [],
                        "model": "deepseek-v4-pro",
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 0,
                            "cache_read_input_tokens": 0,
                            "cache_creation_input_tokens": 0,
                        },
                    },
                }
            ),
            BetaRawContentBlockStartEvent.model_validate(
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_test",
                        "name": "write",
                        "input": {},
                    },
                }
            ),
            BetaRawContentBlockStopEvent.model_validate({"type": "content_block_stop", "index": 0}),
            BetaRawMessageDeltaEvent.model_validate(
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 5},
                }
            ),
        ]
    )

    async def _collect() -> list[message.LLMStreamItem]:
        items: list[message.LLMStreamItem] = []
        async for item in parse_anthropic_stream(
            stream,
            param,
            MetadataTracker(),
            AnthropicStreamStateManager(model_id=str(param.model_id)),
        ):
            items.append(item)
        return items

    items = asyncio.run(_collect())

    assert isinstance(items[-1], message.AssistantMessage)
    parts = items[-1].parts
    assert isinstance(parts[0], message.ThinkingTextPart)
    assert parts[0].text == ""
    assert parts[0].model_id == "deepseek-v4-pro"
    assert isinstance(parts[1], message.ToolCallPart)
