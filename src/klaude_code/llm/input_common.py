"""Common utilities for converting message history to LLM input formats."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMCallParameter, LLMConfigParameter

from klaude_code.const import DEFAULT_MAX_TOKENS
from klaude_code.llm.image import (
    image_data_url_within_single_image_limits,
    image_file_to_data_url,
    image_url_to_request_url,
)
from klaude_code.prompts.messages import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.protocol import message

ImagePart = message.ImageURLPart | message.ImageFilePart
INLINE_IMAGE_PAYLOAD_BUDGET_BYTES = 24 * 1024 * 1024


def _empty_image_parts() -> list[ImagePart]:
    return []


@dataclass
class DeveloperAttachment:
    prefix_text: str = ""
    text: str = ""
    images: list[ImagePart] = field(default_factory=_empty_image_parts)


@dataclass(frozen=True)
class _ImageOccurrence:
    tuple_index: int
    source: Literal["message", "attachment"]
    part_index: int
    request_url: str


def count_images(messages: list[tuple[message.Message, DeveloperAttachment]]) -> int:
    count = 0
    for msg, attachment in messages:
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)):
            count += sum(1 for p in msg.parts if isinstance(p, (message.ImageURLPart, message.ImageFilePart)))
        count += len(attachment.images)
    return count


def image_part_to_request_url(image: ImagePart, *, max_dimension: int) -> str | None:
    if isinstance(image, message.ImageFilePart):
        return image_file_to_data_url(image, max_dimension=max_dimension)
    return image_url_to_request_url(image, max_dimension=max_dimension)


def image_placeholder(image: ImagePart, request_url: str) -> str:
    source = image.source_file_path if isinstance(image, message.ImageURLPart) else image.file_path
    source_text = f" source={source}" if source else ""
    size_kb = len(request_url.encode("utf-8")) / 1024
    if request_url.startswith("data:") and not image_data_url_within_single_image_limits(request_url):
        reason = "single image size limit exceeded"
    else:
        reason = "inline image payload budget exceeded"
    return f"[image omitted from request: {reason};{source_text} size={size_kb:.1f}KB]"


def missing_image_placeholder(image: ImagePart) -> str:
    source = image.source_file_path if isinstance(image, message.ImageURLPart) else image.file_path
    source_text = f" source={source}" if source else ""
    return f"[image unavailable: referenced image file could not be read;{source_text}]"


def _frozen_url_part(image: ImagePart, request_url: str) -> message.ImageURLPart:
    return message.ImageURLPart(
        url=request_url,
        id=image.id if isinstance(image, message.ImageURLPart) else None,
        frozen=True,
        source_file_path=image.source_file_path if isinstance(image, message.ImageURLPart) else image.file_path,
    )


def _collect_image_occurrences(
    attached: list[tuple[message.Message, DeveloperAttachment]],
    *,
    max_dimension: int,
) -> list[_ImageOccurrence]:
    occurrences: list[_ImageOccurrence] = []
    for tuple_index, (msg, attachment) in enumerate(attached):
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)):
            for part_index, part in enumerate(msg.parts):
                if isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
                    request_url = image_part_to_request_url(part, max_dimension=max_dimension)
                    if request_url is not None:
                        occurrences.append(_ImageOccurrence(tuple_index, "message", part_index, request_url))
        for part_index, image in enumerate(attachment.images):
            request_url = image_part_to_request_url(image, max_dimension=max_dimension)
            if request_url is not None:
                occurrences.append(_ImageOccurrence(tuple_index, "attachment", part_index, request_url))
    return occurrences


def _kept_image_occurrences(occurrences: list[_ImageOccurrence]) -> set[tuple[int, str, int]]:
    kept: set[tuple[int, str, int]] = set()
    inline_bytes = 0
    inline_cutoff_reached = False
    for occurrence in reversed(occurrences):
        key = (occurrence.tuple_index, occurrence.source, occurrence.part_index)
        if not occurrence.request_url.startswith("data:"):
            kept.add(key)
            continue
        if not image_data_url_within_single_image_limits(occurrence.request_url):
            continue
        if inline_cutoff_reached:
            continue
        size = len(occurrence.request_url.encode("utf-8"))
        if inline_bytes + size <= INLINE_IMAGE_PAYLOAD_BUDGET_BYTES:
            inline_bytes += size
            kept.add(key)
        else:
            inline_cutoff_reached = True
    return kept


def apply_inline_image_budget(
    attached: list[tuple[message.Message, DeveloperAttachment]],
    *,
    max_dimension: int,
) -> list[tuple[message.Message, DeveloperAttachment]]:
    if count_images(attached) == 0:
        return attached

    occurrences = _collect_image_occurrences(attached, max_dimension=max_dimension)
    occurrence_by_key = {
        (occurrence.tuple_index, occurrence.source, occurrence.part_index): occurrence for occurrence in occurrences
    }
    kept = _kept_image_occurrences(occurrences)

    result: list[tuple[message.Message, DeveloperAttachment]] = []
    for tuple_index, (msg, attachment) in enumerate(attached):
        new_msg = msg
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)):
            new_parts: list[message.Part] = []
            omitted_message_text: list[str] = []
            changed = False
            for part_index, part in enumerate(msg.parts):
                if not isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
                    new_parts.append(part)
                    continue
                key = (tuple_index, "message", part_index)
                occurrence = occurrence_by_key.get(key)
                changed = True
                if occurrence is None:
                    placeholder = missing_image_placeholder(part)
                elif key in kept:
                    new_parts.append(_frozen_url_part(part, occurrence.request_url))
                    continue
                else:
                    placeholder = image_placeholder(part, occurrence.request_url)
                if isinstance(msg, message.ToolResultMessage):
                    omitted_message_text.append(placeholder)
                else:
                    new_parts.append(message.TextPart(text=placeholder))
            if changed:
                update: dict[str, object] = {"parts": new_parts}
                if omitted_message_text and isinstance(msg, message.ToolResultMessage):
                    suffix = "\n".join(omitted_message_text)
                    output_text = msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE
                    update["output_text"] = f"{output_text}\n{suffix}" if output_text else suffix
                new_msg = msg.model_copy(update=update)

        attachment_images: list[ImagePart] = []
        omitted_attachment_text: list[str] = []
        attachment_changed = False
        for part_index, image in enumerate(attachment.images):
            key = (tuple_index, "attachment", part_index)
            occurrence = occurrence_by_key.get(key)
            attachment_changed = True
            if occurrence is None:
                omitted_attachment_text.append(missing_image_placeholder(image))
            elif key in kept:
                attachment_images.append(_frozen_url_part(image, occurrence.request_url))
            else:
                omitted_attachment_text.append(image_placeholder(image, occurrence.request_url))
        if attachment_changed:
            attachment_text = attachment.text
            if omitted_attachment_text:
                suffix = "\n".join(omitted_attachment_text)
                attachment_text = f"{attachment_text}\n{suffix}" if attachment_text else suffix
            attachment = DeveloperAttachment(
                prefix_text=attachment.prefix_text,
                text=attachment_text,
                images=attachment_images,
            )

        result.append((new_msg, attachment))
    return result


def _extract_developer_content(msg: message.DeveloperMessage) -> tuple[str, list[ImagePart]]:
    text_parts: list[str] = []
    images: list[ImagePart] = []
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            text_parts.append(part.text + "\n")
        elif isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
            images.append(part)
    return "".join(text_parts), images


def attach_developer_messages(
    messages: Iterable[message.Message],
) -> list[tuple[message.Message, DeveloperAttachment]]:
    """Attach developer messages to the most recent user/tool message.

    Developer messages are removed from the output list and their text/images are
    attached to the previous user/tool message as out-of-band content for provider input.
    """
    message_list = list(messages)
    attachments = [DeveloperAttachment() for _ in message_list]
    last_user_tool_idx: int | None = None

    for idx, msg in enumerate(message_list):
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)):
            last_user_tool_idx = idx
            continue
        if isinstance(msg, message.DeveloperMessage):
            if last_user_tool_idx is None:
                continue
            dev_text, dev_images = _extract_developer_content(msg)
            attachment = attachments[last_user_tool_idx]
            if msg.attachment_position == "prepend":
                attachment.prefix_text += dev_text
            else:
                attachment.text += dev_text
            attachment.images.extend(dev_images)

    result: list[tuple[message.Message, DeveloperAttachment]] = []
    for idx, msg in enumerate(message_list):
        if isinstance(msg, message.DeveloperMessage):
            continue
        result.append((msg, attachments[idx]))

    return result


def merge_attachment_text(tool_output: str | None, attachment_text: str, *, prefix_text: str = "") -> str:
    """Merge tool output with attachment text."""
    base = tool_output or ""
    if prefix_text:
        base = f"{prefix_text}\n{base}" if base else prefix_text
    if attachment_text:
        base = f"{base}\n{attachment_text}" if base else attachment_text
    return base


def collect_text_content(parts: list[message.Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, message.TextPart))


def build_chat_content_parts(
    msg: message.UserMessage,
    attachment: DeveloperAttachment,
) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    if attachment.prefix_text:
        parts.append({"type": "text", "text": attachment.prefix_text})
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, message.ImageURLPart):
            parts.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(part)}})
        elif isinstance(part, message.ImageFilePart):
            url = image_file_to_data_url(part)
            if url is not None:
                parts.append({"type": "image_url", "image_url": {"url": url}})
    if attachment.text:
        parts.append({"type": "text", "text": attachment.text})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            url = image_file_to_data_url(image)
            if url is not None:
                parts.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(image, message.ImageURLPart):
            parts.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(image)}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return parts


def build_tool_message(
    msg: message.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> dict[str, object]:
    """Build a tool message. Note: image_url in tool message is not supported by
    OpenAI Chat Completions API. Use build_tool_message_for_chat_completions instead.
    """
    merged_text = merge_attachment_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
        prefix_text=attachment.prefix_text,
    )
    content: list[dict[str, object]] = [{"type": "text", "text": merged_text}]
    for part in msg.parts:
        if isinstance(part, message.ImageFilePart):
            if (url := image_file_to_data_url(part)) is not None:
                content.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(part, message.ImageURLPart):
            content.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(part)}})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            if (url := image_file_to_data_url(image)) is not None:
                content.append({"type": "image_url", "image_url": {"url": url}})
        else:
            content.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(image)}})
    return {
        "role": "tool",
        "content": content,
        "tool_call_id": msg.call_id,
    }


def build_tool_message_for_chat_completions(
    msg: message.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> tuple[dict[str, object], dict[str, object] | None]:
    """Build tool message for OpenAI Chat Completions API.

    OpenAI Chat Completions API does not support image_url in tool messages.
    Images are extracted and returned as a separate user message to be appended after the tool message.

    Returns:
        A tuple of (tool_message, optional_user_message_with_images).
        The user_message is None if there are no images.
    """
    merged_text = merge_attachment_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
        prefix_text=attachment.prefix_text,
    )

    # Collect all images
    image_urls: list[dict[str, object]] = []
    for part in msg.parts:
        if isinstance(part, message.ImageFilePart):
            if (url := image_file_to_data_url(part)) is not None:
                image_urls.append({"type": "image_url", "image_url": {"url": url}})
        elif isinstance(part, message.ImageURLPart):
            image_urls.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(part)}})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            if (url := image_file_to_data_url(image)) is not None:
                image_urls.append({"type": "image_url", "image_url": {"url": url}})
        else:
            image_urls.append({"type": "image_url", "image_url": {"url": image_url_to_request_url(image)}})

    tool_message: dict[str, object] = {
        "role": "tool",
        "content": merged_text,
        "tool_call_id": msg.call_id,
    }

    # Build user message with images if any
    user_message: dict[str, object] | None = None
    if image_urls:
        user_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": "Attached image(s) from tool result:"},
                *image_urls,
            ],
        }

    return tool_message, user_message


def build_assistant_common_fields(msg: message.AssistantMessage) -> dict[str, object]:
    result: dict[str, object] = {}

    tool_calls = [part for part in msg.parts if isinstance(part, message.ToolCallPart)]
    if tool_calls:
        result["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": tc.arguments_json,
                },
            }
            for tc in tool_calls
        ]

    thinking_parts = [part for part in msg.parts if isinstance(part, message.ThinkingTextPart)]
    if thinking_parts:
        reasoning_field = next((p.reasoning_field for p in thinking_parts if p.reasoning_field), None)
        if reasoning_field == "reasoning_details":
            # Rebuild structured reasoning_details array (MiniMax M2.5 etc.)
            details: list[dict[str, object]] = []
            for part in msg.parts:
                if isinstance(part, message.ThinkingTextPart):
                    detail: dict[str, object] = {
                        "type": "reasoning.text",
                        "text": part.text,
                        "index": len(details),
                    }
                    if part.id:
                        detail["id"] = part.id
                    if part.format:
                        detail["format"] = part.format
                    details.append(detail)
                elif isinstance(part, message.ThinkingSignaturePart) and part.signature:
                    details.append(
                        {
                            "type": "reasoning.encrypted",
                            "data": part.signature,
                            "format": part.format,
                            "index": len(details),
                        }
                    )
            if details:
                result["reasoning_details"] = details
        else:
            thinking_text = "".join(part.text for part in thinking_parts)
            if thinking_text and reasoning_field:
                result[reasoning_field] = thinking_text

    return result


def split_thinking_parts(
    msg: message.AssistantMessage,
    model_name: str | None,
) -> tuple[list[message.ThinkingTextPart | message.ThinkingSignaturePart], list[str]]:
    native_parts: list[message.ThinkingTextPart | message.ThinkingSignaturePart] = []
    degraded_texts: list[str] = []
    for part in msg.parts:
        if isinstance(part, message.ThinkingTextPart):
            if part.model_id and model_name and part.model_id != model_name:
                degraded_texts.append(part.text)
                continue
            native_parts.append(part)
        elif isinstance(part, message.ThinkingSignaturePart):
            if part.model_id and model_name and part.model_id != model_name:
                continue
            native_parts.append(part)
    return native_parts, degraded_texts


def apply_config_defaults(param: "LLMCallParameter", config: "LLMConfigParameter") -> "LLMCallParameter":
    """Apply config defaults to LLM call parameters."""
    if param.model_id is None:
        param.model_id = config.model_id
    if param.temperature is None:
        param.temperature = config.temperature
    if param.max_tokens is None:
        param.max_tokens = config.max_tokens
    if param.max_tokens is None:
        param.max_tokens = DEFAULT_MAX_TOKENS
    if param.context_limit is None:
        param.context_limit = config.context_limit
    if param.effort is None:
        param.effort = config.effort
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    if param.provider_routing is None:
        param.provider_routing = config.provider_routing
    if not param.fast_mode:
        param.fast_mode = config.fast_mode
    if param.cache_retention is None:
        param.cache_retention = config.cache_retention
    return param
