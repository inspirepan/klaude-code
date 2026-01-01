"""Shared stream processing utilities for Chat Completions streaming.

This module provides reusable primitives for OpenAI-compatible providers:

- ``StreamStateManager``: accumulates assistant content and tool calls.
- ``ReasoningHandlerABC``: provider-specific reasoning extraction + buffering.
- ``parse_chat_completions_stream``: shared stream loop that emits ConversationItems.

OpenRouter uses the same OpenAI Chat Completions API surface but differs in
how reasoning is represented (``reasoning_details`` vs ``reasoning_content``).
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from base64 import b64decode
from binascii import Error as BinasciiError
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

import httpx
import openai
import openai.types
import pydantic
from openai import AsyncStream
from openai.types.chat.chat_completion_chunk import ChatCompletionChunk

from klaude_code import const
from klaude_code.llm.openai_compatible.tool_call_accumulator import BasicToolCallAccumulator, ToolCallAccumulatorABC
from klaude_code.llm.usage import MetadataTracker, convert_usage
from klaude_code.protocol import llm_param, model
from klaude_code.session.session import Session

StreamStage = Literal["waiting", "reasoning", "assistant", "tool"]


_IMAGE_EXT_BY_MIME: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


def _parse_data_url_image(url: str) -> tuple[str, bytes]:
    """Parse a base64 data URL and return (mime_type, decoded_bytes)."""

    header_and_media = url.split(",", 1)
    if len(header_and_media) != 2:
        raise ValueError("Invalid data URL for image: missing comma separator")
    header, base64_data = header_and_media
    if not header.startswith("data:"):
        raise ValueError("Invalid data URL for image: missing data: prefix")
    if ";base64" not in header:
        raise ValueError("Invalid data URL for image: missing base64 marker")

    mime_type = header[5:].split(";", 1)[0]
    base64_payload = base64_data.strip()
    if base64_payload == "":
        raise ValueError("Inline image data is empty")

    try:
        decoded = b64decode(base64_payload, validate=True)
    except (BinasciiError, ValueError) as exc:
        raise ValueError("Inline image data is not valid base64") from exc

    return mime_type, decoded


def _assistant_image_output_dir(session_id: str | None) -> Path:
    if session_id:
        return Session.paths().images_dir(session_id)
    return Path(const.TOOL_OUTPUT_TRUNCATION_DIR) / "images"


def _save_assistant_image(
    *, data_url: str, session_id: str | None, response_id: str | None, image_index: int
) -> model.AssistantImage:
    """Decode a data URL image and save it to the session image artifacts directory."""

    mime_type, decoded = _parse_data_url_image(data_url)

    if len(decoded) > const.IMAGE_OUTPUT_MAX_BYTES:
        decoded_mb = len(decoded) / (1024 * 1024)
        limit_mb = const.IMAGE_OUTPUT_MAX_BYTES / (1024 * 1024)
        raise ValueError(f"Image output size ({decoded_mb:.2f}MB) exceeds limit ({limit_mb:.2f}MB)")

    output_dir = _assistant_image_output_dir(session_id)
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = _IMAGE_EXT_BY_MIME.get(mime_type, ".bin")
    response_part = (response_id or "unknown").replace("/", "_")
    ts = time.time_ns()
    file_path = output_dir / f"img-{response_part}-{image_index}-{ts}{ext}"
    file_path.write_bytes(decoded)

    return model.AssistantImage(
        file_path=str(file_path),
        mime_type=mime_type,
        byte_size=len(decoded),
        sha256=hashlib.sha256(decoded).hexdigest(),
    )


class StreamStateManager:
    """Manages streaming state and provides flush operations for accumulated content.

    This class encapsulates the common state management logic used by both
    OpenAI-compatible and OpenRouter clients, reducing code duplication.
    """

    def __init__(
        self,
        param_model: str,
        response_id: str | None = None,
        reasoning_flusher: Callable[[], list[model.ConversationItem]] | None = None,
    ):
        self.param_model = param_model
        self.response_id = response_id
        self.stage: StreamStage = "waiting"
        self.accumulated_reasoning: list[str] = []
        self.accumulated_content: list[str] = []
        self.accumulated_images: list[model.AssistantImage] = []
        self.accumulated_tool_calls: ToolCallAccumulatorABC = BasicToolCallAccumulator()
        self.emitted_tool_start_indices: set[int] = set()
        self._reasoning_flusher = reasoning_flusher

    def set_response_id(self, response_id: str) -> None:
        """Set the response ID once received from the stream."""
        self.response_id = response_id
        self.accumulated_tool_calls.response_id = response_id  # pyright: ignore[reportAttributeAccessIssue]

    def flush_reasoning(self) -> list[model.ConversationItem]:
        """Flush accumulated reasoning content and return items."""
        if self._reasoning_flusher is not None:
            return self._reasoning_flusher()
        if not self.accumulated_reasoning:
            return []
        item = model.ReasoningTextItem(
            content="".join(self.accumulated_reasoning),
            response_id=self.response_id,
            model=self.param_model,
        )
        self.accumulated_reasoning = []
        return [item]

    def flush_assistant(self) -> list[model.ConversationItem]:
        """Flush accumulated assistant content and return items."""
        if not self.accumulated_content and not self.accumulated_images:
            return []
        item = model.AssistantMessageItem(
            content="".join(self.accumulated_content),
            images=list(self.accumulated_images) if self.accumulated_images else None,
            response_id=self.response_id,
        )
        self.accumulated_content = []
        self.accumulated_images = []
        return [item]

    def flush_tool_calls(self) -> list[model.ToolCallItem]:
        """Flush accumulated tool calls and return items."""
        items: list[model.ToolCallItem] = self.accumulated_tool_calls.get()
        if items:
            self.accumulated_tool_calls.chunks_by_step = []  # pyright: ignore[reportAttributeAccessIssue]
        return items

    def flush_all(self) -> list[model.ConversationItem]:
        """Flush all accumulated content in order: reasoning, assistant, tool calls."""
        items: list[model.ConversationItem] = []
        items.extend(self.flush_reasoning())
        items.extend(self.flush_assistant())
        if self.stage == "tool":
            items.extend(self.flush_tool_calls())
        return items


@dataclass(slots=True)
class ReasoningDeltaResult:
    """Result of processing a single provider delta for reasoning signals."""

    handled: bool
    outputs: list[str | model.ConversationItem]


class ReasoningHandlerABC(ABC):
    """Provider-specific reasoning handler for Chat Completions streaming."""

    @abstractmethod
    def set_response_id(self, response_id: str | None) -> None:
        """Update the response identifier used for emitted items."""

    @abstractmethod
    def on_delta(self, delta: object) -> ReasoningDeltaResult:
        """Process a single delta and return ordered reasoning outputs."""

    @abstractmethod
    def flush(self) -> list[model.ConversationItem]:
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

    def flush(self) -> list[model.ConversationItem]:
        if not self._accumulated:
            return []
        item = model.ReasoningTextItem(
            content="".join(self._accumulated),
            response_id=self._response_id,
            model=self._param_model,
        )
        self._accumulated = []
        return [item]


async def parse_chat_completions_stream(
    stream: AsyncStream[ChatCompletionChunk],
    *,
    param: llm_param.LLMCallParameter,
    metadata_tracker: MetadataTracker,
    reasoning_handler: ReasoningHandlerABC,
    on_event: Callable[[object], None] | None = None,
) -> AsyncGenerator[model.ConversationItem]:
    """Parse OpenAI Chat Completions stream into ConversationItems.

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
                yield model.StartItem(response_id=str(event_id))

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

            # Reasoning
            reasoning_result = reasoning_handler.on_delta(delta)
            if reasoning_result.handled:
                state.stage = "reasoning"
                for output in reasoning_result.outputs:
                    if isinstance(output, str):
                        if not output:
                            continue
                        metadata_tracker.record_token()
                        yield model.ReasoningTextDelta(content=output, response_id=state.response_id)
                    else:
                        yield output

            # Assistant
            images = getattr(delta, "images", None)
            if isinstance(images, list) and images:
                images_list = cast(list[object], images)
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    for item in state.flush_reasoning():
                        yield item
                elif state.stage == "tool":
                    for item in state.flush_tool_calls():
                        yield item
                state.stage = "assistant"
                for image_obj in images_list:
                    url = _extract_image_url(image_obj)
                    if not url:
                        continue
                    if not url.startswith("data:"):
                        # Only data URLs are supported for now.
                        continue
                    try:
                        assistant_image = _save_assistant_image(
                            data_url=url,
                            session_id=param.session_id,
                            response_id=state.response_id,
                            image_index=len(state.accumulated_images),
                        )
                    except ValueError as exc:
                        yield model.StreamErrorItem(error=str(exc))
                        return
                    state.accumulated_images.append(assistant_image)
                    yield model.AssistantImageDelta(response_id=state.response_id, file_path=assistant_image.file_path)

            if (content := getattr(delta, "content", None)) and (state.stage == "assistant" or str(content).strip()):
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    for item in state.flush_reasoning():
                        yield item
                elif state.stage == "tool":
                    for item in state.flush_tool_calls():
                        yield item
                state.stage = "assistant"
                state.accumulated_content.append(str(content))
                yield model.AssistantMessageDelta(
                    content=str(content),
                    response_id=state.response_id,
                )

            # Tool
            if (tool_calls := getattr(delta, "tool_calls", None)) and len(tool_calls) > 0:
                metadata_tracker.record_token()
                if state.stage == "reasoning":
                    for item in state.flush_reasoning():
                        yield item
                elif state.stage == "assistant":
                    for item in state.flush_assistant():
                        yield item
                state.stage = "tool"
                for tc in tool_calls:
                    if tc.index not in state.emitted_tool_start_indices and tc.function and tc.function.name:
                        state.emitted_tool_start_indices.add(tc.index)
                        yield model.ToolCallStartItem(
                            response_id=state.response_id,
                            call_id=tc.id or "",
                            name=tc.function.name,
                        )
                state.accumulated_tool_calls.add(tool_calls)
    except (openai.OpenAIError, httpx.HTTPError) as e:
        yield model.StreamErrorItem(error=f"{e.__class__.__name__} {e!s}")

    flushed_items = state.flush_all()
    if flushed_items:
        metadata_tracker.record_token()
    for item in flushed_items:
        yield item

    metadata_tracker.set_response_id(state.response_id)
    yield metadata_tracker.finalize()
