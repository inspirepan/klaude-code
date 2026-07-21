from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from typing import Any, cast

from openai._models import construct_type_unchecked
from openai.types import responses

from klaude_code.llm.openai_codex.client import build_payload as build_codex_payload
from klaude_code.llm.openai_responses.client import ResponsesLLMStream
from klaude_code.llm.openai_responses.client import build_payload as build_responses_payload
from klaude_code.llm.openai_responses.input import convert_history_to_input
from klaude_code.llm.openrouter.client import build_payload as build_openrouter_payload
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


class _ListAsyncIterator:
    def __init__(self, items: Sequence[object]) -> None:
        self._items = list(items)
        self._index = 0

    def __aiter__(self) -> _ListAsyncIterator:
        return self

    async def __anext__(self) -> object:
        if self._index >= len(self._items):
            raise StopAsyncIteration
        item = self._items[self._index]
        self._index += 1
        return item


def _basic_call_param(input_messages: list[message.Message]) -> llm_param.LLMCallParameter:
    return llm_param.LLMCallParameter(
        input=input_messages,
        model_id="gpt-5.4",
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


def _stream_event(value: dict[str, Any]) -> responses.ResponseStreamEvent:
    return cast(
        responses.ResponseStreamEvent,
        construct_type_unchecked(value=value, type_=cast(Any, responses.ResponseStreamEvent)),
    )


def _assistant_item_phase(input_items: object) -> str | None:
    assert isinstance(input_items, list)
    for raw_item in cast(list[object], input_items):
        if not isinstance(raw_item, dict):
            continue
        item = cast(dict[str, Any], raw_item)
        if item.get("type") == "message" and item.get("role") == "assistant":
            phase = item.get("phase")
            assert phase is None or isinstance(phase, str)
            return phase
    return None


def test_responses_input_preserves_assistant_phase() -> None:
    history: list[message.Message] = [
        message.AssistantMessage(
            parts=[message.TextPart(text="draft")],
            phase="commentary",
        )
    ]

    items = convert_history_to_input(history, model_name="gpt-5.4")
    assert _assistant_item_phase(items) == "commentary"


def test_responses_stream_keeps_phase_from_output_item_done() -> None:
    events = [
        _stream_event(
            {
                "type": "response.output_item.done",
                "output_index": 0,
                "sequence_number": 1,
                "item": {
                    "type": "message",
                    "id": "msg_1",
                    "role": "assistant",
                    "status": "completed",
                    "phase": "commentary",
                    "content": [{"type": "output_text", "text": "draft", "annotations": []}],
                },
            }
        ),
        _stream_event(
            {
                "type": "response.completed",
                "sequence_number": 2,
                "response": {
                    "id": "resp_1",
                    "created_at": 0,
                    "status": "completed",
                    "output": [],
                },
            }
        ),
    ]
    stream = ResponsesLLMStream(
        cast(Any, _ListAsyncIterator(events)),
        param=_basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])]),
        metadata_tracker=MetadataTracker(),
    )

    items = _collect_stream(stream)
    final_message = next(item for item in items if isinstance(item, message.AssistantMessage))
    assert final_message.phase == "commentary"


def test_responses_stream_keeps_phase_from_completed_response_output() -> None:
    events = [
        _stream_event(
            {
                "type": "response.completed",
                "sequence_number": 1,
                "response": {
                    "id": "resp_1",
                    "created_at": 0,
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "id": "msg_1",
                            "role": "assistant",
                            "status": "completed",
                            "phase": "final_answer",
                            "content": [{"type": "output_text", "text": "final", "annotations": []}],
                        }
                    ],
                },
            }
        )
    ]
    stream = ResponsesLLMStream(
        cast(Any, _ListAsyncIterator(events)),
        param=_basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])]),
        metadata_tracker=MetadataTracker(),
    )

    items = _collect_stream(stream)
    final_message = next(item for item in items if isinstance(item, message.AssistantMessage))
    assert final_message.phase == "final_answer"


def test_responses_and_codex_payload_replay_assistant_phase() -> None:
    param = _basic_call_param(
        [
            message.UserMessage(parts=[message.TextPart(text="hi")]),
            message.AssistantMessage(parts=[message.TextPart(text="draft")], phase="commentary"),
        ]
    )

    responses_payload = build_responses_payload(param)
    codex_payload = build_codex_payload(param)

    assert _assistant_item_phase(responses_payload.get("input")) == "commentary"
    assert _assistant_item_phase(codex_payload.get("input")) == "commentary"


def test_responses_payload_omits_empty_reasoning_summary() -> None:
    param = _basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])])
    param.thinking = llm_param.Thinking(reasoning_effort="high")

    payload = build_responses_payload(param)

    assert payload.get("reasoning") == {"effort": "high"}


def test_responses_codex_and_openrouter_payload_include_reasoning_mode() -> None:
    param = _basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])])
    param.model_id = "gpt-5.6-sol"
    param.thinking = llm_param.Thinking(
        reasoning_effort="max",
        reasoning_mode="pro",
        reasoning_context="all_turns",
        reasoning_summary="detailed",
    )

    responses_payload = build_responses_payload(param)
    codex_payload = build_codex_payload(param)
    _, openrouter_extra_body, _ = build_openrouter_payload(param)

    expected = {"effort": "max", "mode": "pro", "context": "all_turns", "summary": "detailed"}
    assert responses_payload.get("reasoning") == expected
    assert codex_payload.get("reasoning") == expected
    assert openrouter_extra_body.get("reasoning") == {"effort": "max", "mode": "pro", "context": "all_turns"}


def test_responses_and_codex_payload_use_supported_prompt_cache_fields_for_gpt56() -> None:
    param = _basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])])
    param.model_id = "gpt-5.6-sol"

    responses_payload = build_responses_payload(param)
    codex_payload = build_codex_payload(param)

    assert responses_payload.get("prompt_cache_options") == {"ttl": "30m"}
    assert "prompt_cache_retention" not in responses_payload
    assert "prompt_cache_retention" not in codex_payload
    assert "prompt_cache_options" not in codex_payload


def test_responses_and_codex_payload_keep_prompt_cache_retention_for_older_gpt() -> None:
    param = _basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])])
    param.model_id = "gpt-5.5"

    responses_payload = build_responses_payload(param)
    codex_payload = build_codex_payload(param)

    assert responses_payload.get("prompt_cache_retention") == "24h"
    assert codex_payload.get("prompt_cache_retention") == "24h"
    assert "prompt_cache_options" not in responses_payload
    assert "prompt_cache_options" not in codex_payload


def test_codex_payload_sets_priority_service_tier_for_fast_mode() -> None:
    param = _basic_call_param([message.UserMessage(parts=[message.TextPart(text="hi")])])
    param.fast_mode = True

    codex_payload = build_codex_payload(param)

    assert codex_payload.get("service_tier") == "priority"
