"""Common utilities for converting message history to LLM input formats."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMCallParameter, LLMConfigParameter

from klaude_code.const import DEFAULT_MAX_TOKENS, EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.llm.image import image_file_to_data_url
from klaude_code.protocol import message

ImagePart = message.ImageURLPart | message.ImageFilePart


def _empty_image_parts() -> list[ImagePart]:
    return []


@dataclass
class DeveloperAttachment:
    prefix_text: str = ""
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


def merge_reminder_text(tool_output: str | None, reminder_text: str, *, prefix_text: str = "") -> str:
    """Merge tool output with reminder text."""
    base = tool_output or ""
    if prefix_text:
        base = f"{prefix_text}\n{base}" if base else prefix_text
    if reminder_text:
        base = f"{base}\n{reminder_text}" if base else reminder_text
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
    """Build a tool message. Note: image_url in tool message is not supported by
    OpenAI Chat Completions API. Use build_tool_message_for_chat_completions instead.
    """
    merged_text = merge_reminder_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
        prefix_text=attachment.prefix_text,
    )
    content: list[dict[str, object]] = [{"type": "text", "text": merged_text}]
    for part in msg.parts:
        if isinstance(part, message.ImageFilePart):
            content.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(part)}})
        elif isinstance(part, message.ImageURLPart):
            content.append({"type": "image_url", "image_url": {"url": part.url}})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            content.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(image)}})
        else:
            content.append({"type": "image_url", "image_url": {"url": image.url}})
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
    merged_text = merge_reminder_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
        prefix_text=attachment.prefix_text,
    )

    # Collect all images
    image_urls: list[dict[str, object]] = []
    for part in msg.parts:
        if isinstance(part, message.ImageFilePart):
            image_urls.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(part)}})
        elif isinstance(part, message.ImageURLPart):
            image_urls.append({"type": "image_url", "image_url": {"url": part.url}})
    for image in attachment.images:
        if isinstance(image, message.ImageFilePart):
            image_urls.append({"type": "image_url", "image_url": {"url": image_file_to_data_url(image)}})
        else:
            image_urls.append({"type": "image_url", "image_url": {"url": image.url}})

    # If only images (no text), use placeholder
    has_text = bool(merged_text.strip())
    tool_content = merged_text if has_text else ""

    tool_message: dict[str, object] = {
        "role": "tool",
        # list format required by openrouter/input.py _add_cache_control()
        "content": [{"type": "text", "text": tool_content}],
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
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    if param.provider_routing is None:
        param.provider_routing = config.provider_routing
    return param
