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
