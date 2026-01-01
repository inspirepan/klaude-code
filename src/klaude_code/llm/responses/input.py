# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportAssignmentType=false

from typing import Any

from openai.types import responses

from klaude_code.llm.input_common import DeveloperAttachment, attach_developer_messages, merge_reminder_text
from klaude_code.protocol import llm_param, model


def _build_user_content_parts(
    user: model.UserMessage,
    attachment: DeveloperAttachment,
) -> list[responses.ResponseInputContentParam]:
    parts: list[responses.ResponseInputContentParam] = []
    for part in user.parts:
        if isinstance(part, model.TextPart):
            parts.append({"type": "input_text", "text": part.text})
        elif isinstance(part, model.ImageURLPart):
            parts.append({"type": "input_image", "detail": "auto", "image_url": part.url})
    if attachment.text:
        parts.append({"type": "input_text", "text": attachment.text})
    for image in attachment.images:
        parts.append({"type": "input_image", "detail": "auto", "image_url": image.url})
    if not parts:
        parts.append({"type": "input_text", "text": ""})
    return parts


def _build_tool_result_item(
    tool: model.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> responses.ResponseInputItemParam:
    content_parts: list[responses.ResponseInputContentParam] = []
    text_output = merge_reminder_text(
        tool.output_text or "<system-reminder>Tool ran without output or errors</system-reminder>",
        attachment.text,
    )
    if text_output:
        content_parts.append({"type": "input_text", "text": text_output})
    images = [part for part in tool.parts if isinstance(part, model.ImageURLPart)] + attachment.images
    for image in images:
        content_parts.append({"type": "input_image", "detail": "auto", "image_url": image.url})

    item: dict[str, Any] = {
        "type": "function_call_output",
        "call_id": tool.call_id,
        "output": content_parts,
    }
    return item


def convert_history_to_input(
    history: list[model.Message],
    model_name: str | None = None,
) -> responses.ResponseInputParam:
    """Convert a list of messages to response input params."""
    items: list[responses.ResponseInputItemParam] = []

    degraded_thinking_texts: list[str] = []

    for message, attachment in attach_developer_messages(history):
        match message:
            case model.SystemMessage():
                system_text = "\n".join(part.text for part in message.parts)
                if system_text:
                    items.append(
                        {
                            "type": "message",
                            "role": "system",
                            "content": [
                                {
                                    "type": "input_text",
                                    "text": system_text,
                                }
                            ],
                        }
                    )
            case model.UserMessage():
                items.append(
                    {
                        "type": "message",
                        "role": "user",
                        "id": message.id,
                        "content": _build_user_content_parts(message, attachment),
                    }
                )
            case model.ToolResultMessage():
                items.append(_build_tool_result_item(message, attachment))
            case model.AssistantMessage():
                assistant_text_parts: list[responses.ResponseInputContentParam] = []
                pending_thinking_text: str | None = None
                pending_signature: str | None = None

                def flush_text(*, _message_id: str = message.id) -> None:
                    nonlocal assistant_text_parts
                    if not assistant_text_parts:
                        return
                    items.append(
                        {
                            "type": "message",
                            "role": "assistant",
                            "id": _message_id,
                            "content": assistant_text_parts,
                        }
                    )
                    assistant_text_parts = []

                def emit_reasoning() -> None:
                    nonlocal pending_thinking_text, pending_signature
                    if pending_thinking_text is None:
                        return
                    items.append(convert_reasoning_inputs(pending_thinking_text, pending_signature))
                    pending_thinking_text = None
                    pending_signature = None

                for part in message.parts:
                    if isinstance(part, model.ThinkingTextPart):
                        if part.model_id and model_name and part.model_id != model_name:
                            degraded_thinking_texts.append(part.text)
                            continue
                        emit_reasoning()
                        pending_thinking_text = part.text
                        continue
                    if isinstance(part, model.ThinkingSignaturePart):
                        if part.model_id and model_name and part.model_id != model_name:
                            continue
                        pending_signature = part.signature
                        continue

                    emit_reasoning()
                    if isinstance(part, model.TextPart):
                        assistant_text_parts.append({"type": "output_text", "text": part.text})
                    elif isinstance(part, model.ToolCallPart):
                        flush_text()
                        items.append(
                            {
                                "type": "function_call",
                                "name": part.tool_name,
                                "arguments": part.arguments_json,
                                "call_id": part.call_id,
                                "id": part.call_id,
                            }
                        )

                emit_reasoning()
                flush_text()
            case _:
                continue

    if degraded_thinking_texts:
        degraded_item: responses.ResponseInputItemParam = {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>",
                }
            ],
        }
        items.insert(0, degraded_item)

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
    return result


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
) -> list[responses.ToolParam]:
    if tools is None:
        return []
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        for tool in tools
    ]
