"""Shared stream processing utilities for Chat Completions streaming.

This module provides reusable primitives for OpenAI-compatible providers:

- ``StreamStateManager``: accumulates assistant content and tool calls.
- ``ReasoningHandlerABC``: provider-specific reasoning extraction + buffering.
- ``parse_chat_completions_stream``: shared stream loop that emits stream/history items.

OpenRouter uses the same OpenAI Chat Completions API surface but differs in
how reasoning is represented (``reasoning_details`` vs ``reasoning_content``).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from typing import Any, Literal, cast

import httpx
import openai
import openai.types
import pydantic
from openai import AsyncStream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from klaude_code.llm.image import save_assistant_image
from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, message, model

StreamStage = Literal["waiting", "reasoning", "assistant", "tool"]


class StreamStateManager:
    """Manages streaming state and provides flush operations for accumulated content.

    This class encapsulates the common state management logic used by both
    OpenAI-compatible and OpenRouter clients, reducing code duplication.
    """

    def __init__(
        self,
        param_model: str,
        response_id: str | None = None,
        reasoning_flusher: Callable[[], list[message.Part]] | None = None,
    ):
        self.param_model = param_model
        self.response_id = response_id
        self.stage: StreamStage = "waiting"
        self.accumulated_content: list[str] = []
        self.accumulated_images: list[message.ImageFilePart] = []
        self.accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        self.emitted_tool_start_indices: set[int] = set()
        self._reasoning_flusher = reasoning_flusher
        self.parts: list[message.Part] = []
        self.stop_reason: model.StopReason | None = None

    def set_response_id(self, response_id: str) -> None:
        """Set the response ID once received from the stream."""
        self.response_id = response_id
        self.accumulated_tool_calls.response_id = response_id  # pyright: ignore[reportAttributeAccessIssue]

    def flush_reasoning(self) -> None:
        """Flush accumulated reasoning content into parts."""
        if self._reasoning_flusher is not None:
            self.parts.extend(self._reasoning_flusher())

    def flush_assistant(self) -> None:
        """Flush accumulated assistant content into parts."""
        if not self.accumulated_content and not self.accumulated_images:
            return
        if self.accumulated_content:
            self.parts.append(message.TextPart(text="".join(self.accumulated_content)))
        if self.accumulated_images:
            self.parts.extend(self.accumulated_images)
        self.accumulated_content = []
        self.accumulated_images = []
        return

    def flush_tool_calls(self) -> None:
        """Flush accumulated tool calls into parts."""
        items = self.accumulated_tool_calls.get()
        if items:
            self.parts.extend(items)
            self.accumulated_tool_calls.chunks_by_step = []  # pyright: ignore[reportAttributeAccessIssue]

    def flush_all(self) -> list[message.Part]:
        """Flush all accumulated content in order: reasoning, assistant, tool calls."""
        self.flush_reasoning()
        self.flush_assistant()
        if self.stage == "tool":
            self.flush_tool_calls()
        return list(self.parts)


@dataclass(slots=True)
class ReasoningDeltaResult:
    """Result of processing a single provider delta for reasoning signals."""

    handled: bool
    outputs: list[str | message.Part]


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


class DefaultReasoningHandler(ReasoningHandlerABC):
    """Handles OpenAI-compatible reasoning fields (reasoning_content / reasoning)."""

    def __init__(
        self,
        *,
        param_model: str,
        response_id: str | None,
    ) -> None:
        self._param_model = param_model
        self._response_id = response_id
        self._accumulated: list[str] = []

    def set_response_id(self, response_id: str | None) -> None:
        self._response_id = response_id

    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        reasoning_content = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None) or ""
        if not reasoning_content:
            return ReasoningDeltaResult(handled=False, outputs=[])
        text = str(reasoning_content)
        self._accumulated.append(text)
        return ReasoningDeltaResult(handled=True, outputs=[text])

    def flush(self) -> list[message.Part]:
        if not self._accumulated:
            return []
        item = message.ThinkingTextPart(
            text="".join(self._accumulated),
            model_id=self._param_model,
        )
        self._accumulated = []
        return [item]


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
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    reasoning_handler: ReasoningHandlerABC,
    on_event: Callable[[object], None] | None = None,
) -> AsyncGenerator[message.LLMStreamItem]:
    """Parse OpenAI Chat Completions stream into stream items.

    This is shared by OpenAI-compatible and OpenRouter clients.
    """

    state = StreamStateManager(
        param_model=str(param.model),
        reasoning_flusher=reasoning_handler.flush,
    )

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
                yield message.StartItem(response_id=str(event_id))

            if (event_usage := getattr(event, "usage", None)) is not None:
                metadata_tracker.set_usage(convert_usage(event_usage, param.context_limit, param.max_tokens))
            if event_model := getattr(event, "model", None):
                metadata_tracker.set_model_name(str(event_model))
            if provider := getattr(event, "provider", None):
                metadata_tracker.set_provider(str(provider))

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
                state.stage = "reasoning"
                for output in reasoning_result.outputs:
                    if isinstance(output, str):
                        if not output:
                            continue
                        metadata_tracker.record_token()
                        yield message.ThinkingTextDelta(content=output, response_id=state.response_id)
                    else:
                        state.parts.append(output)

            # Assistant
            images = getattr(delta, "images", None)
            if isinstance(images, list) and images:
                images_list = cast(list[object], images)
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    state.flush_reasoning()
                elif state.stage == "tool":
                    state.flush_tool_calls()
                state.stage = "assistant"
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
                            image_index=len(state.accumulated_images),
                        )
                    except ValueError as exc:
                        yield message.StreamErrorItem(error=str(exc))
                        return
                    state.accumulated_images.append(assistant_image)
                    yield message.AssistantImageDelta(response_id=state.response_id, file_path=assistant_image.file_path)

            if (content := getattr(delta, "content", None)) and (state.stage == "assistant" or str(content).strip()):
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    state.flush_reasoning()
                elif state.stage == "tool":
                    state.flush_tool_calls()
                state.stage = "assistant"
                state.accumulated_content.append(str(content))
                yield message.AssistantMessageDelta(
                    content=str(content),
                    response_id=state.response_id,
                )

            # Tool
            if (tool_calls := getattr(delta, "tool_calls", None)) and len(tool_calls) > 0:
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    state.flush_reasoning()
                elif state.stage == "assistant":
                    state.flush_assistant()
                state.stage = "tool"
                for tc in tool_calls:
                    if tc.index not in state.emitted_tool_start_indices and tc.function and tc.function.name:
                        state.emitted_tool_start_indices.add(tc.index)
                        yield message.ToolCallStartItem(
                            response_id=state.response_id,
                            call_id=tc.id or "",
                            name=tc.function.name,
                        )
                state.accumulated_tool_calls.add(tool_calls)
    except (openai.OpenAIError, httpx.HTTPError) as e:
        yield message.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")

    parts = state.flush_all()
    if parts:
        metadata_tracker.record_token()
    metadata_tracker.set_response_id(state.response_id)
    metadata = metadata_tracker.finalize()
    if parts:
        yield message.AssistantMessage(
            parts=parts,
            response_id=state.response_id,
            usage=metadata,
            stop_reason=state.stop_reason,
        )
    yield metadata
