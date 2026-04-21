# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportUnknownVariableType=false

import json
from typing import Literal, cast

from anthropic.types.beta.beta_base64_image_source_param import BetaBase64ImageSourceParam
from anthropic.types.beta.beta_content_block_param import BetaContentBlockParam
from anthropic.types.beta.beta_image_block_param import BetaImageBlockParam
from anthropic.types.beta.beta_message_param import BetaMessageParam
from anthropic.types.beta.beta_text_block_param import BetaTextBlockParam
from anthropic.types.beta.beta_tool_param import BetaToolParam
from anthropic.types.beta.beta_tool_result_block_param import BetaToolResultBlockParam
from anthropic.types.beta.beta_tool_use_block_param import BetaToolUseBlockParam
from anthropic.types.beta.beta_url_image_source_param import BetaURLImageSourceParam

from klaude_code.llm.image import (
    MAX_IMAGE_DIMENSION,
    image_file_to_data_url,
    image_url_to_request_url,
    parse_data_url,
)
from klaude_code.llm.input_common import (
    DeveloperAttachment,
    ImagePart,
    attach_developer_messages,
    merge_attachment_text,
    split_thinking_parts,
)
from klaude_code.prompts.messages import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.protocol import llm_param, message
from klaude_code.protocol.model_id import model_supports_eager_input_streaming, model_supports_unsigned_thinking
from klaude_code.protocol.system_prompt import SYSTEM_PROMPT_DYNAMIC_BOUNDARY, split_system_prompt_for_cache

AllowedMediaType = Literal["image/png", "image/jpeg", "image/gif", "image/webp"]
_INLINE_IMAGE_MEDIA_TYPES: tuple[AllowedMediaType, ...] = (
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
)

_MANY_IMAGE_DIMENSION = 2000
_MANY_IMAGE_THRESHOLD = 2


def _count_images(messages: list[tuple[message.Message, DeveloperAttachment]]) -> int:
    count = 0
    for msg, attachment in messages:
        if isinstance(msg, (message.UserMessage, message.ToolResultMessage)):
            count += sum(1 for p in msg.parts if isinstance(p, (message.ImageURLPart, message.ImageFilePart)))
        count += len(attachment.images)
    return count


def _image_part_to_block(image: ImagePart, *, max_dimension: int) -> BetaImageBlockParam | None:
    url = (
        image_file_to_data_url(image, max_dimension=max_dimension)
        if isinstance(image, message.ImageFilePart)
        else image_url_to_request_url(image, max_dimension=max_dimension)
    )
    if url is None:
        return None
    if url.startswith("data:"):
        media_type, base64_payload, _ = parse_data_url(url)
        if media_type not in _INLINE_IMAGE_MEDIA_TYPES:
            raise ValueError(f"Unsupported inline image media type: {media_type}")
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
    msg: message.UserMessage,
    attachment: DeveloperAttachment,
    *,
    max_dimension: int,
) -> BetaMessageParam:
    blocks: list[BetaTextBlockParam | BetaImageBlockParam] = []
    if attachment.prefix_text:
        blocks.append(cast(BetaTextBlockParam, {"type": "text", "text": attachment.prefix_text}))
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            blocks.append(cast(BetaTextBlockParam, {"type": "text", "text": part.text}))
        elif (
            isinstance(part, (message.ImageURLPart, message.ImageFilePart))
            and (block := _image_part_to_block(part, max_dimension=max_dimension)) is not None
        ):
            blocks.append(block)
    if attachment.text:
        blocks.append(cast(BetaTextBlockParam, {"type": "text", "text": attachment.text}))
    for image in attachment.images:
        if (block := _image_part_to_block(image, max_dimension=max_dimension)) is not None:
            blocks.append(block)
    if not blocks:
        blocks.append(cast(BetaTextBlockParam, {"type": "text", "text": ""}))
    return {"role": "user", "content": blocks}


def _tool_message_to_block(
    msg: message.ToolResultMessage,
    attachment: DeveloperAttachment,
    *,
    max_dimension: int,
) -> BetaToolResultBlockParam:
    """Convert a single tool result message to a tool_result block."""
    tool_content: list[BetaTextBlockParam | BetaImageBlockParam] = []
    merged_text = merge_attachment_text(
        msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
        prefix_text=attachment.prefix_text,
    )
    tool_content.append(cast(BetaTextBlockParam, {"type": "text", "text": merged_text}))
    for image in [part for part in msg.parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart))]:
        if (block := _image_part_to_block(image, max_dimension=max_dimension)) is not None:
            tool_content.append(block)
    for image in attachment.images:
        if (block := _image_part_to_block(image, max_dimension=max_dimension)) is not None:
            tool_content.append(block)
    return {
        "type": "tool_result",
        "tool_use_id": msg.call_id,
        "is_error": msg.status != "success",
        "content": tool_content,
    }


def _tool_blocks_to_message(blocks: list[BetaToolResultBlockParam]) -> BetaMessageParam:
    """Convert one or more tool_result blocks to a single user message."""
    return {
        "role": "user",
        "content": blocks,
    }


def _assistant_message_to_message(msg: message.AssistantMessage, model_name: str | None) -> BetaMessageParam:
    content: list[BetaContentBlockParam] = []
    current_thinking_content: str | None = None
    native_thinking_parts, _ = split_thinking_parts(msg, model_name)
    native_thinking_ids = {id(part) for part in native_thinking_parts}
    supports_unsigned = model_supports_unsigned_thinking(model_name)

    def _degraded_thinking_block(text: str) -> BetaTextBlockParam | None:
        stripped = text.strip()
        if not stripped:
            return None
        return cast(
            BetaTextBlockParam,
            {
                "type": "text",
                "text": f"<thinking>\n{stripped}\n</thinking>",
            },
        )

    def _flush_thinking() -> None:
        nonlocal current_thinking_content
        if current_thinking_content is None:
            return
        if supports_unsigned:
            content.append(
                cast(
                    BetaContentBlockParam,
                    {"type": "thinking", "thinking": current_thinking_content},
                )
            )
        elif block := _degraded_thinking_block(current_thinking_content):
            content.append(block)
        current_thinking_content = None

    for part in msg.parts:
        if isinstance(part, message.ThinkingTextPart):
            if id(part) not in native_thinking_ids:
                if block := _degraded_thinking_block(part.text):
                    content.append(block)
                continue
            current_thinking_content = part.text
            continue
        if isinstance(part, message.ThinkingSignaturePart):
            if id(part) not in native_thinking_ids:
                continue
            if part.signature:
                content.append(
                    cast(
                        BetaContentBlockParam,
                        {
                            "type": "thinking",
                            "thinking": current_thinking_content or "",
                            "signature": part.signature,
                        },
                    )
                )
                current_thinking_content = None
            elif supports_unsigned:
                content.append(
                    cast(
                        BetaContentBlockParam,
                        {"type": "thinking", "thinking": current_thinking_content or ""},
                    )
                )
                current_thinking_content = None
            continue

        _flush_thinking()
        if isinstance(part, message.TextPart):
            content.append(cast(BetaTextBlockParam, {"type": "text", "text": part.text}))
        elif isinstance(part, message.ToolCallPart):
            tool_input: dict[str, object] = {}
            if part.arguments_json:
                try:
                    parsed = json.loads(part.arguments_json)
                except json.JSONDecodeError:
                    parsed = {"_raw": part.arguments_json}
                tool_input = cast(dict[str, object], parsed) if isinstance(parsed, dict) else {"_value": parsed}

            content.append(
                cast(
                    BetaToolUseBlockParam,
                    {
                        "type": "tool_use",
                        "id": part.call_id,
                        "name": part.tool_name,
                        "input": tool_input,
                    },
                )
            )

    _flush_thinking()

    return {"role": "assistant", "content": content}


def _add_cache_control(messages: list[BetaMessageParam], *, ttl: Literal["5m", "1h"] = "5m") -> None:
    if len(messages) > 0:
        last_message = messages[-1]
        content_list = list(last_message.get("content", []))
        if content_list:
            last_content_part = content_list[-1]
            if last_content_part.get("type", "") in ["text", "tool_result", "tool_use"]:
                cache_control: dict[str, str] = {"type": "ephemeral"}
                if ttl == "1h":
                    cache_control["ttl"] = "1h"
                last_content_part["cache_control"] = cache_control  # type: ignore


def convert_history_to_input(
    history: list[message.Message],
    model_name: str | None,
    *,
    cache_ttl: Literal["5m", "1h"] = "5m",
) -> list[BetaMessageParam]:
    """Convert a list of messages to beta message params."""
    attached = attach_developer_messages(history)
    image_count = _count_images(attached)
    max_dim = _MANY_IMAGE_DIMENSION if image_count >= _MANY_IMAGE_THRESHOLD else MAX_IMAGE_DIMENSION

    messages: list[BetaMessageParam] = []
    pending_tool_blocks: list[BetaToolResultBlockParam] = []

    def flush_tool_blocks() -> None:
        nonlocal pending_tool_blocks
        if pending_tool_blocks:
            messages.append(_tool_blocks_to_message(pending_tool_blocks))
            pending_tool_blocks = []

    for msg, attachment in attached:
        match msg:
            case message.ToolResultMessage():
                pending_tool_blocks.append(_tool_message_to_block(msg, attachment, max_dimension=max_dim))
            case message.UserMessage():
                flush_tool_blocks()
                messages.append(_user_message_to_message(msg, attachment, max_dimension=max_dim))
            case message.AssistantMessage():
                flush_tool_blocks()
                messages.append(_assistant_message_to_message(msg, model_name))
            case message.SystemMessage():
                continue
            case _:
                continue

    flush_tool_blocks()
    _add_cache_control(messages, ttl=cache_ttl)
    return messages


def convert_system_to_input(
    system: str | None,
    system_messages: list[message.SystemMessage] | None = None,
    *,
    cache_ttl: Literal["5m", "1h"] = "5m",
) -> list[BetaTextBlockParam]:
    blocks: list[BetaTextBlockParam] = []
    has_explicit_cache_block = False

    def _cache_control() -> dict[str, str]:
        control: dict[str, str] = {"type": "ephemeral"}
        if cache_ttl == "1h":
            control["ttl"] = "1h"
        return control

    def append_block(text: str, *, cache_control: bool) -> None:
        nonlocal has_explicit_cache_block
        block: BetaTextBlockParam = {"type": "text", "text": text}
        if cache_control:
            block["cache_control"] = _cache_control()  # type: ignore[typeddict-item]
            has_explicit_cache_block = True
        blocks.append(block)

    static_system, dynamic_system = split_system_prompt_for_cache(system)
    has_boundary = bool(system and SYSTEM_PROMPT_DYNAMIC_BOUNDARY in system)
    if static_system:
        append_block(static_system, cache_control=True)
    if dynamic_system:
        append_block(dynamic_system, cache_control=True)
    elif system and not has_boundary:
        append_block(system, cache_control=True)

    if system_messages:
        for msg in system_messages:
            system_text = "\n".join(part.text for part in msg.parts)
            if system_text:
                append_block(system_text, cache_control=False)

    if not blocks:
        return []
    if not has_explicit_cache_block:
        blocks[-1]["cache_control"] = _cache_control()  # type: ignore[typeddict-item]
    return blocks


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
    model_name: str | None,
) -> list[BetaToolParam]:
    if tools is None:
        return []
    enable_eager_input_streaming = model_supports_eager_input_streaming(model_name)
    return [
        cast(
            BetaToolParam,
            {
                "input_schema": tool.parameters,
                "type": "custom",
                "name": tool.name,
                "description": tool.description,
                **({"eager_input_streaming": True} if enable_eager_input_streaming else {}),
            },
        )
        for tool in tools
    ]
