# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportUnknownVariableType=false

import json
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Literal, cast

from anthropic.types.beta.beta_base64_image_source_param import BetaBase64ImageSourceParam
from anthropic.types.beta.beta_image_block_param import BetaImageBlockParam
from anthropic.types.beta.beta_message_param import BetaMessageParam
from anthropic.types.beta.beta_text_block_param import BetaTextBlockParam
from anthropic.types.beta.beta_tool_param import BetaToolParam
from anthropic.types.beta.beta_url_image_source_param import BetaURLImageSourceParam

from klaude_code.llm.input_common import DeveloperAttachment, attach_developer_messages, merge_reminder_text
from klaude_code.protocol import llm_param, model

AllowedMediaType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
_INLINE_IMAGE_MEDIA_TYPES: tuple[AllowedMediaType, ...] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)


def _image_part_to_block(image: model.ImageURLPart) -> BetaImageBlockParam:
    url = image.url
    if url.startswith("data:"):
        header_and_media = url.split(",", 1)
        if len(header_and_media) != 2:
            raise ValueError("Invalid data URL for image: missing comma separator")
        header, base64_data = header_and_media
        if ";base64" not in header:
            raise ValueError("Invalid data URL for image: missing base64 marker")
        media_type = header[5:].split(";", 1)[0]
        if media_type not in _INLINE_IMAGE_MEDIA_TYPES:
            raise ValueError(f"Unsupported inline image media type: {media_type}")
        base64_payload = base64_data.strip()
        if base64_payload == "":
            raise ValueError("Inline image data is empty")
        try:
            b64decode(base64_payload, validate=True)
        except (BinasciiError, ValueError) as exc:
            raise ValueError("Inline image data is not valid base64") from exc
        source = cast(
            BetaBase64ImageSourceParam,
            {
                "type": "base64",
                "media_type": media_type,
                "data": base64_payload,
            },
        )
        return {"type": "image", "source": source}

    source_url: BetaURLImageSourceParam = {"type": "url", "url": url}
    return {"type": "image", "source": source_url}


def _user_message_to_message(
    message: model.UserMessage,
    attachment: DeveloperAttachment,
) -> BetaMessageParam:
    blocks: list[BetaTextBlockParam | BetaImageBlockParam] = []
    for part in message.parts:
        if isinstance(part, model.TextPart):
            blocks.append({"type": "text", "text": part.text})
        elif isinstance(part, model.ImageURLPart):
            blocks.append(_image_part_to_block(part))
    if attachment.text:
        blocks.append({"type": "text", "text": attachment.text})
    for image in attachment.images:
        blocks.append(_image_part_to_block(image))
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return {"role": "user", "content": blocks}


def _tool_message_to_block(
    message: model.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> dict[str, object]:
    """Convert a single tool result message to a tool_result block."""
    tool_content: list[BetaTextBlockParam | BetaImageBlockParam] = []
    merged_text = merge_reminder_text(
        message.output_text or "<system-reminder>Tool ran without output or errors</system-reminder>",
        attachment.text,
    )
    tool_content.append({"type": "text", "text": merged_text})
    for image in [part for part in message.parts if isinstance(part, model.ImageURLPart)]:
        tool_content.append(_image_part_to_block(image))
    for image in attachment.images:
        tool_content.append(_image_part_to_block(image))
    return {
        "type": "tool_result",
        "tool_use_id": message.call_id,
        "is_error": message.status != "success",
        "content": tool_content,
    }


def _tool_blocks_to_message(blocks: list[dict[str, object]]) -> BetaMessageParam:
    """Convert one or more tool_result blocks to a single user message."""
    return {
        "role": "user",
        "content": blocks,
    }


def _assistant_message_to_message(message: model.AssistantMessage, model_name: str | None) -> BetaMessageParam:
    content: list[dict[str, object]] = []
    current_thinking_content: str | None = None
    degraded_thinking_texts: list[str] = []

    def _flush_thinking() -> None:
        nonlocal current_thinking_content
        if current_thinking_content is None:
            return
        content.append({"type": "thinking", "thinking": current_thinking_content})
        current_thinking_content = None

    for part in message.parts:
        if isinstance(part, model.ThinkingTextPart):
            if part.model_id and model_name and part.model_id != model_name:
                degraded_thinking_texts.append(part.text)
                continue
            current_thinking_content = part.text
            continue
        if isinstance(part, model.ThinkingSignaturePart):
            if part.model_id and model_name and part.model_id != model_name:
                continue
            if current_thinking_content is not None and part.signature:
                content.append(
                    {
                        "type": "thinking",
                        "thinking": current_thinking_content,
                        "signature": part.signature,
                    }
                )
                current_thinking_content = None
            continue

        _flush_thinking()
        if isinstance(part, model.TextPart):
            content.append({"type": "text", "text": part.text})
        elif isinstance(part, model.ToolCallPart):
            content.append(
                {
                    "type": "tool_use",
                    "id": part.call_id,
                    "name": part.tool_name,
                    "input": json.loads(part.arguments_json) if part.arguments_json else None,
                }
            )

    _flush_thinking()

    if degraded_thinking_texts:
        degraded_text = "<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"
        content.insert(0, {"type": "text", "text": degraded_text})

    return {"role": "assistant", "content": content}


def _add_cache_control(messages: list[BetaMessageParam]) -> None:
    if len(messages) > 0:
        last_message = messages[-1]
        content_list = list(last_message.get("content", []))
        if content_list:
            last_content_part = content_list[-1]
            if last_content_part.get("type", "") in ["text", "tool_result", "tool_use"]:
                last_content_part["cache_control"] = {"type": "ephemeral"}  # type: ignore


def convert_history_to_input(
    history: list[model.Message],
    model_name: str | None,
) -> list[BetaMessageParam]:
    """Convert a list of messages to beta message params."""
    messages: list[BetaMessageParam] = []
    pending_tool_blocks: list[dict[str, object]] = []

    def flush_tool_blocks() -> None:
        nonlocal pending_tool_blocks
        if pending_tool_blocks:
            messages.append(_tool_blocks_to_message(pending_tool_blocks))
            pending_tool_blocks = []

    for message, attachment in attach_developer_messages(history):
        match message:
            case model.ToolResultMessage():
                pending_tool_blocks.append(_tool_message_to_block(message, attachment))
            case model.UserMessage():
                flush_tool_blocks()
                messages.append(_user_message_to_message(message, attachment))
            case model.AssistantMessage():
                flush_tool_blocks()
                messages.append(_assistant_message_to_message(message, model_name))
            case model.SystemMessage():
                continue
            case _:
                continue

    flush_tool_blocks()
    _add_cache_control(messages)
    return messages


def convert_system_to_input(
    system: str | None, system_messages: list[model.SystemMessage] | None = None
) -> list[BetaTextBlockParam]:
    parts: list[str] = []
    if system:
        parts.append(system)
    if system_messages:
        for message in system_messages:
            parts.append("\n".join(part.text for part in message.parts))
    if not parts:
        return []
    return [{"type": "text", "text": "\n".join(parts), "cache_control": {"type": "ephemeral"}}]


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
) -> list[BetaToolParam]:
    if tools is None:
        return []
    return [
        {
            "input_schema": tool.parameters,
            "type": "custom",
            "name": tool.name,
            "description": tool.description,
        }
        for tool in tools
    ]
