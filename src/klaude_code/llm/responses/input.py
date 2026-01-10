# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportAssignmentType=false

from typing import Any, cast

from openai.types import responses

from klaude_code.const import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.llm.image import image_file_to_data_url
from klaude_code.llm.input_common import (
    DeveloperAttachment,
    attach_developer_messages,
    merge_reminder_text,
    split_thinking_parts,
)
from klaude_code.protocol import llm_param, message


def _image_to_url(image: message.ImageURLPart | message.ImageFilePart) -> str:
    if isinstance(image, message.ImageFilePart):
        return image_file_to_data_url(image)
    return image.url


def _build_user_content_parts(
    user: message.UserMessage,
    attachment: DeveloperAttachment,
) -> list[responses.ResponseInputContentParam]:
    parts: list[responses.ResponseInputContentParam] = []
    for part in user.parts:
        if isinstance(part, message.TextPart):
            parts.append(cast(responses.ResponseInputContentParam, {"type": "input_text", "text": part.text}))
        elif isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
            parts.append(
                cast(
                    responses.ResponseInputContentParam,
                    {"type": "input_image", "detail": "auto", "image_url": _image_to_url(part)},
                )
            )
    if attachment.text:
        parts.append(cast(responses.ResponseInputContentParam, {"type": "input_text", "text": attachment.text}))
    for image in attachment.images:
        parts.append(
            cast(
                responses.ResponseInputContentParam,
                {"type": "input_image", "detail": "auto", "image_url": _image_to_url(image)},
            )
        )
    if not parts:
        parts.append(cast(responses.ResponseInputContentParam, {"type": "input_text", "text": ""}))
    return parts


def _build_tool_result_item(
    tool: message.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> responses.ResponseInputItemParam:
    content_parts: list[responses.ResponseInputContentParam] = []
    text_output = merge_reminder_text(
        tool.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
        attachment.text,
    )
    if text_output:
        content_parts.append(cast(responses.ResponseInputContentParam, {"type": "input_text", "text": text_output}))
    images: list[message.ImageURLPart | message.ImageFilePart] = [
        part for part in tool.parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart))
    ]
    images.extend(attachment.images)
    for image in images:
        content_parts.append(
            cast(
                responses.ResponseInputContentParam,
                {"type": "input_image", "detail": "auto", "image_url": _image_to_url(image)},
            )
        )

    item: dict[str, Any] = {
        "type": "function_call_output",
        "call_id": tool.call_id,
        "output": content_parts,
    }
    return cast(responses.ResponseInputItemParam, item)


def convert_history_to_input(
    history: list[message.Message],
    model_name: str | None = None,
) -> responses.ResponseInputParam:
    """Convert a list of messages to response input params."""
    items: list[responses.ResponseInputItemParam] = []

    for msg, attachment in attach_developer_messages(history):
        match msg:
            case message.SystemMessage():
                system_text = "\n".join(part.text for part in msg.parts)
                if system_text:
                    items.append(
                        cast(
                            responses.ResponseInputItemParam,
                            {
                                "type": "message",
                                "role": "system",
                                "content": [
                                    cast(
                                        responses.ResponseInputContentParam,
                                        {"type": "input_text", "text": system_text},
                                    )
                                ],
                            },
                        )
                    )
            case message.UserMessage():
                items.append(
                    cast(
                        responses.ResponseInputItemParam,
                        {
                            "type": "message",
                            "role": "user",
                            "content": _build_user_content_parts(msg, attachment),
                        },
                    )
                )
            case message.ToolResultMessage():
                items.append(_build_tool_result_item(msg, attachment))
            case message.AssistantMessage():
                assistant_text_parts: list[responses.ResponseOutputTextParam] = []
                pending_thinking_text: str | None = None
                pending_signature: str | None = None
                native_thinking_parts, degraded_for_message = split_thinking_parts(msg, model_name)
                native_thinking_ids = {id(part) for part in native_thinking_parts}
                if degraded_for_message:
                    degraded_text = "<thinking>\n" + "\n".join(degraded_for_message) + "\n</thinking>"
                    assistant_text_parts.append(
                        cast(
                            responses.ResponseOutputTextParam,
                            {"type": "output_text", "text": degraded_text},
                        )
                    )

                def flush_text() -> None:
                    nonlocal assistant_text_parts
                    if not assistant_text_parts:
                        return
                    items.append(
                        cast(
                            responses.ResponseInputItemParam,
                            {
                                "type": "message",
                                "role": "assistant",
                                "content": assistant_text_parts,
                            },
                        )
                    )
                    assistant_text_parts = []

                def emit_reasoning() -> None:
                    nonlocal pending_thinking_text, pending_signature
                    if pending_thinking_text is None and pending_signature is None:
                        return
                    items.append(convert_reasoning_inputs(pending_thinking_text, pending_signature))
                    pending_thinking_text = None
                    pending_signature = None

                for part in msg.parts:
                    if isinstance(part, message.ThinkingTextPart):
                        if id(part) not in native_thinking_ids:
                            continue
                        emit_reasoning()
                        pending_thinking_text = part.text
                        continue
                    if isinstance(part, message.ThinkingSignaturePart):
                        if id(part) not in native_thinking_ids:
                            continue
                        pending_signature = part.signature
                        continue

                    emit_reasoning()
                    if isinstance(part, message.TextPart):
                        assistant_text_parts.append(
                            cast(
                                responses.ResponseOutputTextParam,
                                {"type": "output_text", "text": part.text},
                            )
                        )
                    elif isinstance(part, message.ToolCallPart):
                        flush_text()
                        items.append(
                            cast(
                                responses.ResponseInputItemParam,
                                {
                                    "type": "function_call",
                                    "name": part.tool_name,
                                    "arguments": part.arguments_json,
                                    "call_id": part.call_id,
                                    "id": part.id,
                                },
                            )
                        )

                emit_reasoning()
                flush_text()
            case _:
                continue

    return items


def convert_reasoning_inputs(text_content: str | None, signature: str | None) -> responses.ResponseInputItemParam:
    result: dict[str, Any] = {"type": "reasoning", "content": None}
    result["summary"] = [
        {
            "type": "summary_text",
            "text": text_content or "",
        }
    ]
    if signature:
        result["encrypted_content"] = signature
    return cast(responses.ResponseInputItemParam, result)


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
) -> list[responses.ToolParam]:
    if tools is None:
        return []
    return [
        cast(
            responses.ToolParam,
            {
                "type": "function",
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        )
        for tool in tools
    ]
