import asyncio

from anthropic.types.beta.beta_raw_message_delta_event import BetaRawMessageDeltaEvent
from anthropic.types.beta.beta_raw_message_start_event import BetaRawMessageStartEvent

from klaude_code.const import ANTHROPIC_BETA_INTERLEAVED_THINKING
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


def test_build_payload_omits_empty_betas_for_adaptive_sonnet_46() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert "betas" not in payload


def test_build_payload_includes_interleaved_beta_when_needed() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-3-7-sonnet-20250219",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=1024),
    )

    payload = build_payload(param)

    assert ANTHROPIC_BETA_INTERLEAVED_THINKING in payload.get("betas", [])


def test_build_payload_enables_eager_input_streaming_for_claude_tools() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="claude-sonnet-4-6",
        tools=_dummy_tools(),
    )

    payload = build_payload(param)

    assert payload["tools"][0]["eager_input_streaming"] is True


def test_build_payload_does_not_enable_eager_input_streaming_for_non_claude_models() -> None:
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="deepseek-reasoner",
        tools=_dummy_tools(),
    )

    payload = build_payload(param)

    assert "eager_input_streaming" not in payload["tools"][0]


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
