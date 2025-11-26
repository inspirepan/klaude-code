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

from klaude_code.protocol import llm_parameter, model
from klaude_code.protocol.model import ReasoningEncryptedItem, ReasoningTextItem

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


def _append_user_content_blocks(
    blocks: list[BetaTextBlockParam | BetaImageBlockParam],
    item: model.MessageItem,
) -> None:
    if isinstance(item, model.UserMessageItem):
        if item.content is not None:
            blocks.append({"type": "text", "text": item.content + "\n"})
        for image in item.images or []:
            blocks.append(_image_part_to_block(image))
    elif isinstance(item, model.DeveloperMessageItem):
        if item.content is not None:
            blocks.append({"type": "text", "text": item.content + "\n"})
        for image in item.images or []:
            blocks.append(_image_part_to_block(image))


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
    for group_kind, group in model.group_response_items_gen(history):
        match group_kind:
            case "user":
                content_blocks: list[BetaTextBlockParam | BetaImageBlockParam] = []
                for item in group:
                    _append_user_content_blocks(content_blocks, item)
                if not content_blocks:
                    content_blocks.append({"type": "text", "text": ""})
                messages.append({"role": "user", "content": content_blocks})
            case "tool":
                if len(group) == 0 or not isinstance(group[0], model.ToolResultItem):
                    continue
                tool_result = group[0]
                reminders: list[model.DeveloperMessageItem] = [
                    i for i in group if isinstance(i, model.DeveloperMessageItem)
                ]
                reminders_str = "\n" + "\n".join(i.content for i in reminders if i.content)
                tool_content: list[BetaTextBlockParam | BetaImageBlockParam] = []
                tool_text = (tool_result.output or "") + reminders_str
                tool_content.append({"type": "text", "text": tool_text})
                for image in tool_result.images or []:
                    tool_content.append(_image_part_to_block(image))
                for reminder in reminders:
                    for image in reminder.images or []:
                        tool_content.append(_image_part_to_block(image))

                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": tool_result.call_id,
                                "is_error": tool_result.status == "error",
                                "content": tool_content,
                            }
                        ],
                    }
                )
            case "assistant":
                assistant_message = {
                    "role": "assistant",
                    "content": [],
                }
                current_reasoning_content: str | None = None

                for item in group:
                    match item:
                        case model.AssistantMessageItem() as a:
                            assistant_message["content"].append(
                                {
                                    "type": "text",
                                    "text": a.content,
                                }
                            )
                        case model.ToolCallItem() as t:
                            assistant_message["content"].append(
                                {
                                    "type": "tool_use",
                                    "id": t.call_id,
                                    "name": t.name,
                                    "input": json.loads(t.arguments) if t.arguments else None,
                                }
                            )
                        case ReasoningEncryptedItem() as r:
                            if r.encrypted_content and len(r.encrypted_content) > 0 and model_name == r.model:
                                assistant_message["content"].append(
                                    {
                                        "type": "thinking",
                                        "thinking": current_reasoning_content or "",
                                        "signature": r.encrypted_content,
                                    }
                                )
                                current_reasoning_content = None
                        case ReasoningTextItem() as r:
                            if model_name != r.model:
                                continue
                            current_reasoning_content = r.content
                        case _:
                            pass

                if (
                    len(current_reasoning_content or "") > 0
                ):  # Moonshot.ai's Kimi does not always send reasoning signatures
                    assistant_message["content"] = [
                        {
                            "type": "thinking",
                            "thinking": current_reasoning_content,
                        }
                    ].extend(assistant_message["content"])

                messages.append(assistant_message)
            case "other":
                pass

    # Cache control
    if len(messages) > 0:
        last_message = messages[-1]
        content_list = list(last_message.get("content", []))
        if content_list:
            last_content_part = content_list[-1]
            if last_content_part.get("type", "") in ["text", "tool_result", "tool_use"]:
                last_content_part["cache_control"] = {"type": "ephemeral"}  # type: ignore
    return messages


def convert_system_to_input(system: str | None) -> list[BetaTextBlockParam]:
    if system is None:
        return []
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def convert_tool_schema(
    tools: list[llm_parameter.ToolSchema] | None,
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
