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

from klaude_code.llm.input_common import AssistantGroup, ToolGroup, UserGroup, merge_reminder_text, parse_message_groups
from klaude_code.protocol import llm_param, model

AllowedMediaType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
_INLINE_IMAGE_MEDIA_TYPES: tuple[AllowedMediaType, ...] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)


def _image_part_to_block(image: model.ImageURLPart) -> BetaImageBlockParam:
    url = image.image_url.url
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


def _user_group_to_message(group: UserGroup) -> BetaMessageParam:
    blocks: list[BetaTextBlockParam | BetaImageBlockParam] = []
    for text in group.text_parts:
        blocks.append({"type": "text", "text": text + "\n"})
    for image in group.images:
        blocks.append(_image_part_to_block(image))
    if not blocks:
        blocks.append({"type": "text", "text": ""})
    return {"role": "user", "content": blocks}


def _tool_group_to_block(group: ToolGroup) -> dict[str, object]:
    """Convert a single ToolGroup to a tool_result block."""
    tool_content: list[BetaTextBlockParam | BetaImageBlockParam] = []
    merged_text = merge_reminder_text(
        group.tool_result.output or "<system-reminder>Tool ran without output or errors</system-reminder>",
        group.reminder_texts,
    )
    tool_content.append({"type": "text", "text": merged_text})
    for image in group.tool_result.images or []:
        tool_content.append(_image_part_to_block(image))
    for image in group.reminder_images:
        tool_content.append(_image_part_to_block(image))
    return {
        "type": "tool_result",
        "tool_use_id": group.tool_result.call_id,
        "is_error": group.tool_result.status == "error",
        "content": tool_content,
    }


def _tool_groups_to_message(groups: list[ToolGroup]) -> BetaMessageParam:
    """Convert one or more ToolGroups to a single user message with multiple tool_result blocks."""
    return {
        "role": "user",
        "content": [_tool_group_to_block(group) for group in groups],
    }


def _assistant_group_to_message(group: AssistantGroup, model_name: str | None) -> BetaMessageParam:
    content: list[dict[str, object]] = []
    current_reasoning_content: str | None = None
    degraded_thinking_texts: list[str] = []

    # Process reasoning items in original order so that text and
    # encrypted parts are paired correctly for the given model.
    # For cross-model scenarios, degrade thinking to plain text.
    for item in group.reasoning_items:
        if isinstance(item, model.ReasoningTextItem):
            if model_name != item.model:
                # Cross-model: collect thinking text for degradation
                if item.content:
                    degraded_thinking_texts.append(item.content)
            else:
                current_reasoning_content = item.content
        else:
            # Same model: preserve signature
            if model_name == item.model and item.encrypted_content and len(item.encrypted_content) > 0:
                content.append(
                    {
                        "type": "thinking",
                        "thinking": current_reasoning_content or "",
                        "signature": item.encrypted_content,
                    }
                )
                current_reasoning_content = None

    # Moonshot.ai's Kimi does not always send reasoning signatures;
    # if we saw reasoning text without any matching encrypted item,
    # emit it as a plain thinking block.
    if len(current_reasoning_content or "") > 0:
        content.insert(0, {"type": "thinking", "thinking": current_reasoning_content})

    # Cross-model: degrade thinking to plain text with <thinking> tags
    if degraded_thinking_texts:
        degraded_text = "<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"
        content.insert(0, {"type": "text", "text": degraded_text})

    if group.text_content:
        content.append({"type": "text", "text": group.text_content})

    for tc in group.tool_calls:
        content.append(
            {
                "type": "tool_use",
                "id": tc.call_id,
                "name": tc.name,
                "input": json.loads(tc.arguments) if tc.arguments else None,
            }
        )

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
    history: list[model.ConversationItem],
    model_name: str | None,
) -> list[BetaMessageParam]:
    """
    Convert a list of conversation items to a list of beta message params.

    Args:
        history: List of conversation items.
        model_name: Model name. Used to verify that signatures are valid for the same model
    """
    messages: list[BetaMessageParam] = []
    pending_tool_groups: list[ToolGroup] = []

    def flush_tool_groups() -> None:
        nonlocal pending_tool_groups
        if pending_tool_groups:
            messages.append(_tool_groups_to_message(pending_tool_groups))
            pending_tool_groups = []

    for group in parse_message_groups(history):
        match group:
            case UserGroup():
                flush_tool_groups()
                messages.append(_user_group_to_message(group))
            case ToolGroup():
                pending_tool_groups.append(group)
            case AssistantGroup():
                flush_tool_groups()
                messages.append(_assistant_group_to_message(group, model_name))

    flush_tool_groups()
    _add_cache_control(messages)
    return messages


def convert_system_to_input(system: str | None) -> list[BetaTextBlockParam]:
    if system is None:
        return []
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


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
