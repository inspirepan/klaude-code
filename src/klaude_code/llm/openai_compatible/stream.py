"""Shared stream processing utilities for Chat Completions streaming.

This module provides reusable primitives for OpenAI-compatible providers:

- ``StreamStateManager``: accumulates assistant parts in stream order.
- ``ReasoningHandlerABC``: provider-specific reasoning extraction.
- ``OpenAILLMStream``: LLMStream implementation for OpenAI-compatible clients.

OpenRouter uses the same OpenAI Chat Completions API surface but differs in
how reasoning is represented (``reasoning_details`` vs ``reasoning_content``).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, cast

import httpx
import openai
import openai.types
import pydantic
from openai import AsyncStream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from klaude_code.llm.client import LLMStreamABC
from klaude_code.llm.image import save_assistant_image
from klaude_code.llm.stream_parts import (
    append_text_part,
    append_thinking_text_part,
    build_partial_message,
    build_partial_parts,
)
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.log import log_debug
from klaude_code.protocol import llm_param, message, model


def normalize_tool_name(name: str) -> str:
    """Normalize tool name from Gemini-3 format.

    Gemini-3 sometimes returns tool names in format like 'tool_Edit_mUoY2p3W3r3z8uO5P2nZ'.
    This function extracts the actual tool name (e.g., 'Edit').
    """
    match = re.match(r"^tool_([A-Za-z]+)_[A-Za-z0-9]+$", name)
    if match:
        normalized = match.group(1)
        log_debug(f"Gemini-3 tool name normalized: {name} -> {normalized}", style="yellow")
        return normalized
    return name


class StreamStateManager:
    """Manages streaming state and accumulates parts in stream order.

    The persisted AssistantMessage is built directly from ``assistant_parts``.
    ``get_partial_message()`` returns a best-effort message on cancellation.
    """

    def __init__(
        self,
        param_model: str,
        response_id: str | None = None,
    ):
        self.param_model = param_model
        self.response_id = response_id
        self.assistant_parts: list[message.Part] = []
        self._image_index: int = 0
        self._tool_part_index_by_tc_index: dict[int, int] = {}
        self._emitted_tool_start_indices: set[int] = set()
        self.stop_reason: model.StopReason | None = None

    def set_response_id(self, response_id: str) -> None:
        """Set the response ID once received from the stream."""
        self.response_id = response_id

    def append_thinking_text(self, text: str, *, reasoning_field: str | None = None) -> None:
        """Append thinking text, merging with the previous ThinkingTextPart when possible."""
        append_thinking_text_part(
            self.assistant_parts, text, model_id=self.param_model, reasoning_field=reasoning_field
        )

    def append_text(self, text: str) -> None:
        """Append assistant text, merging with the previous TextPart when possible."""
        append_text_part(self.assistant_parts, text)

    def append_image(self, image_part: message.ImageFilePart) -> None:
        self.assistant_parts.append(image_part)
        self._image_index += 1

    def upsert_tool_call(self, *, tc_index: int, call_id: str | None, name: str | None, arguments: str | None) -> None:
        """Insert a ToolCallPart at first sight and keep updating its fields.

        Chat Completions streams tool call fields incrementally (name/id first,
        then argument fragments). We keep the ToolCallPart in-place to preserve
        stream order in the persisted AssistantMessage.
        """

        part_index = self._tool_part_index_by_tc_index.get(tc_index)
        if part_index is None:
            tool_part = message.ToolCallPart(
                call_id=call_id or "",
                tool_name=normalize_tool_name(name or ""),
                arguments_json=arguments or "",
            )
            self.assistant_parts.append(tool_part)
            self._tool_part_index_by_tc_index[tc_index] = len(self.assistant_parts) - 1
            return

        existing = self.assistant_parts[part_index]
        if not isinstance(existing, message.ToolCallPart):
            return

        if call_id and not existing.call_id:
            existing.call_id = call_id
        if name and not existing.tool_name:
            existing.tool_name = normalize_tool_name(name)
        if arguments:
            existing.arguments_json += arguments

    def mark_tool_start_emitted(self, tc_index: int) -> bool:
        """Return True if this is the first time we emit ToolCallStartDelta for this index."""
        if tc_index in self._emitted_tool_start_indices:
            return False
        self._emitted_tool_start_indices.add(tc_index)
        return True

    def next_image_index(self) -> int:
        return self._image_index

    def get_partial_parts(self) -> list[message.Part]:
        """Get accumulated parts excluding tool calls, with thinking degraded.

        Filters out ToolCallPart and applies degrade_thinking_to_text.
        """
        return build_partial_parts(self.assistant_parts)

    def get_partial_message(self) -> message.AssistantMessage | None:
        """Build a partial AssistantMessage from accumulated state.

        Filters out tool calls and degrades thinking content for safety.
        Returns None if no content has been accumulated.
        """
        return build_partial_message(self.assistant_parts, response_id=self.response_id)


@dataclass(slots=True)
class ReasoningDeltaResult:
    """Result of processing a single provider delta for reasoning signals."""

    handled: bool
    outputs: list[str | message.Part]
    reasoning_field: str | None = None  # Original field name: reasoning_content, reasoning, reasoning_text


class ReasoningHandlerABC(ABC):
    """Provider-specific reasoning handler for Chat Completions streaming."""

    @abstractmethod
    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""

    @abstractmethod
    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        """Process a single delta and return ordered reasoning outputs."""

    @abstractmethod
    def flush(self) -> list[message.Part]:
        """Flush buffered reasoning content (usually at stage transition/finalize)."""


REASONING_FIELDS = ("reasoning_content", "reasoning", "reasoning_text")


class DefaultReasoningHandler(ReasoningHandlerABC):
    """Handles OpenAI-compatible reasoning fields (reasoning_content / reasoning / reasoning_text)."""

    def __init__(
        self,
        *,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id
        self._reasoning_field: str | None = None

    def set_response_id(self, response_id: str | None) -> None:
        self._response_id = response_id

    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        for field_name in REASONING_FIELDS:
            content = getattr(delta, field_name, None)
            if content:
                if self._reasoning_field is None:
                    self._reasoning_field = field_name
                text = str(content)
                return ReasoningDeltaResult(handled=True, outputs=[text], reasoning_field=self._reasoning_field)
        return ReasoningDeltaResult(handled=False, outputs=[])

    def flush(self) -> list[message.Part]:
        return []


def _map_finish_reason(reason: str) -> model.StopReason | None:
    mapping: dict[str, model.StopReason] = {
        "stop": "stop",
        "length": "length",
        "tool_calls": "tool_use",
        "content_filter": "error",
        "error": "error",
        "cancelled": "aborted",
    }
    return mapping.get(reason)


async def parse_chat_completions_stream(
    stream: AsyncStream[ChatCompletionChunk],
    *,
    state: StreamStateManager,
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    reasoning_handler: ReasoningHandlerABC,
    on_event: Callable[[object], None] | None = None,
    provider_prefix: str = "",
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse OpenAI Chat Completions stream into stream items.

    This is shared by OpenAI-compatible and OpenRouter clients.
    The state parameter allows external access to accumulated content
    for cancellation scenarios.
    """

    def _extract_image_url(image_obj: object) -> str | None:
        image_url = getattr(image_obj, "image_url", None)
        if image_url is not None:
            url = getattr(image_url, "url", None)
            return str(url) if isinstance(url, str) else None
        if isinstance(image_obj, dict):
            image_dict = cast(dict[str, Any], image_obj)
            url_dict_raw = image_dict.get("image_url")
            if isinstance(url_dict_raw, dict):
                url_dict = cast(dict[str, Any], url_dict_raw)
                url_raw = url_dict.get("url")
                return url_raw if isinstance(url_raw, str) else None
        return None

    try:
        async for event in stream:
            if on_event is not None:
                on_event(event)

            if not state.response_id and (event_id := getattr(event, "id", None)):
                state.set_response_id(str(event_id))
                reasoning_handler.set_response_id(str(event_id))

            if (event_usage := getattr(event, "usage", None)) is not None:
                metadata_tracker.set_usage(convert_usage(event_usage, param.context_limit, param.max_tokens))
            if event_model := getattr(event, "model", None):
                metadata_tracker.set_model_name(str(event_model))
            if provider := getattr(event, "provider", None):
                metadata_tracker.set_provider(f"{provider_prefix}{provider}")

            choices = cast(Any, getattr(event, "choices", None))
            if not choices:
                continue

            # Support Moonshot Kimi K2's usage field in choice
            choice0 = choices[0]
            if choice_usage := getattr(choice0, "usage", None):
                try:
                    usage = openai.types.CompletionUsage.model_validate(choice_usage)
                    metadata_tracker.set_usage(convert_usage(usage, param.context_limit, param.max_tokens))
                except pydantic.ValidationError:
                    pass

            delta = cast(Any, getattr(choice0, "delta", None))
            if delta is None:
                continue

            finish_reason = getattr(choice0, "finish_reason", None)
            if isinstance(finish_reason, str):
                state.stop_reason = _map_finish_reason(finish_reason)

            # Reasoning
            reasoning_result = reasoning_handler.on_delta(delta)
            if reasoning_result.handled:
                for output in reasoning_result.outputs:
                    if isinstance(output, str):
                        if not output:
                            continue
                        metadata_tracker.record_token()
                        state.append_thinking_text(output, reasoning_field=reasoning_result.reasoning_field)
                        yield message.ThinkingTextDelta(content=output, response_id=state.response_id)
                    else:
                        state.assistant_parts.append(output)

            # Assistant
            images = getattr(delta, "images", None)
            if isinstance(images, list) and images:
                images_list = cast(list[object], images)
                metadata_tracker.record_token()
                for image_obj in images_list:
                    url = _extract_image_url(image_obj)
                    if not url:
                        continue
                    if not url.startswith("data:"):
                        # Only data URLs are supported for now.
                        continue
                    try:
                        assistant_image = save_assistant_image(
                            data_url=url,
                            session_id=param.session_id,
                            response_id=state.response_id,
                            image_index=state.next_image_index(),
                        )
                    except ValueError as exc:
                        yield message.StreamErrorItem(error=str(exc))
                        return
                    state.append_image(assistant_image)
                    yield message.AssistantImageDelta(
                        response_id=state.response_id, file_path=assistant_image.file_path
                    )

            content_str = str(content) if (content := getattr(delta, "content", None)) is not None else ""

            if content_str and (
                (state.assistant_parts and isinstance(state.assistant_parts[-1], message.TextPart))
                or content_str.strip()
            ):
                metadata_tracker.record_token()
                state.append_text(content_str)
                yield message.AssistantTextDelta(
                    content=content_str,
                    response_id=state.response_id,
                )

            # Tool
            if (tool_calls := getattr(delta, "tool_calls", None)) and len(tool_calls) > 0:
                metadata_tracker.record_token()
                for tc in tool_calls:
                    tc_index = getattr(tc, "index", None)
                    if not isinstance(tc_index, int):
                        continue
                    fn = getattr(tc, "function", None)
                    fn_name = getattr(fn, "name", None) if fn is not None else None
                    fn_args = getattr(fn, "arguments", None) if fn is not None else None
                    tc_id = getattr(tc, "id", None)

                    if fn_name and state.mark_tool_start_emitted(tc_index):
                        yield message.ToolCallStartDelta(
                            response_id=state.response_id,
                            call_id=str(tc_id or ""),
                            name=str(fn_name),
                        )
                    state.upsert_tool_call(
                        tc_index=tc_index,
                        call_id=str(tc_id) if isinstance(tc_id, str) else None,
                        name=str(fn_name) if isinstance(fn_name, str) else None,
                        arguments=str(fn_args) if isinstance(fn_args, str) else None,
                    )
    except (openai.OpenAIError, httpx.HTTPError) as e:
        yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")
        state.stop_reason = "error"

    # On error, use partial parts (excluding incomplete tool calls) for potential prefill on retry
    parts = state.get_partial_parts() if state.stop_reason == "error" else list(state.assistant_parts)
    if parts:
        metadata_tracker.record_token()
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    yield message.AssistantMessage(
        parts=parts,
        response_id=state.response_id,
        usage=metadata,
        stop_reason=state.stop_reason,
    )


class OpenAILLMStream(LLMStreamABC):
    """LLMStream implementation for OpenAI-compatible clients."""

    def __init__(
        self,
        stream: AsyncStream[ChatCompletionChunk],
        *,
        param: llm_param.LLMCallParameter,
        metadata_tracker: MetadataTracker,
        reasoning_handler: ReasoningHandlerABC,
        on_event: Callable[[object], None] | None = None,
        provider_prefix: str = "",
    ) -> None:
        self._stream = stream
        self._param = param
        self._metadata_tracker = metadata_tracker
        self._reasoning_handler = reasoning_handler
        self._on_event = on_event
        self._provider_prefix = provider_prefix
        self._state = StreamStateManager(
            param_model=str(param.model_id),
        )
        self._completed = False

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        async for item in parse_chat_completions_stream(
            self._stream,
            state=self._state,
            param=self._param,
            metadata_tracker=self._metadata_tracker,
            reasoning_handler=self._reasoning_handler,
            on_event=self._on_event,
            provider_prefix=self._provider_prefix,
        ):
            if isinstance(item, message.AssistantMessage):
                self._completed = True
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        if self._completed:
            return None
        return self._state.get_partial_message()
