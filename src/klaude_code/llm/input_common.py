"""Common utilities for converting message history to LLM input formats."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMCallParameter, LLMConfigParameter

from klaude_code.const import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.llm.image import image_file_to_data_url
from klaude_code.protocol import message

ImagePart = message.ImageURLPart | message.ImageFilePart


def _empty_image_parts() -> list[ImagePart]:
    return []


@dataclass
class DeveloperAttachment:
    text: str = ""
    images: list[ImagePart] = field(default_factory=_empty_image_parts)


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
            attachment.text += dev_text
            attachment.images.extend(dev_images)

    result: list[tuple[message.Message, DeveloperAttachment]] = []
    for idx, msg in enumerate(message_list):
        if isinstance(msg, message.DeveloperMessage):
            continue
        result.append((msg, attachments[idx]))

    return result


def merge_reminder_text(tool_output: str | None, reminder_text: str) -> str:
    """Merge tool output with reminder text."""
    base = tool_output or ""
    if reminder_text:
        base += "\n" + reminder_text
    return base


def collect_text_content(parts: list[message.Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, message.TextPart))


def build_chat_content_parts(
    msg: message.UserMessage,
    attachment: DeveloperAttachment,
) -> list[dict[str, object]]:
    parts: list[dict[str, object]] = []
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, message.ImageURLPart):
            parts.append({"type": "image_url", "image_url": {"url": part.url}})
        elif isinstance(part, message.ImageFilePart):
            parts.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(part)}})
    if attachment.text:
        parts.append({"type": "text", "text": attachment.text})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            parts.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(image)}})
        else:
            parts.append({"type": "image_url", "image_url": {"url": image.url}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return parts


def build_tool_message(
    msg: message.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> dict[str, object]:
    merged_text = merge_reminder_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
    )
    return {
        "role": "tool",
        "content": [{"type": "text", "text": merged_text}],
        "tool_call_id": msg.call_id,
    }


def build_assistant_common_fields(
    msg: message.AssistantMessage,
    *,
    image_to_data_url: Callable[[message.ImageFilePart], str],
) -> dict[str, object]:
    result: dict[str, object] = {}
    images = [part for part in msg.parts if isinstance(part, message.ImageFilePart)]
    if images:
        result["images"] = [
            {
                "image_url": {
                    "url": image_to_data_url(image),
                }
            }
            for image in images
        ]

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
        thinking_text = "".join(part.text for part in thinking_parts)
        reasoning_field = next((p.reasoning_field for p in thinking_parts if p.reasoning_field), None)
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
    if param.context_limit is None:
        param.context_limit = config.context_limit
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    if param.modalities is None:
        param.modalities = config.modalities
    if param.image_config is None:
        param.image_config = config.image_config
    elif config.image_config is not None:
        # Merge field-level: param overrides config defaults
        if param.image_config.aspect_ratio is None:
            param.image_config.aspect_ratio = config.image_config.aspect_ratio
        if param.image_config.image_size is None:
            param.image_config.image_size = config.image_config.image_size
    return param
