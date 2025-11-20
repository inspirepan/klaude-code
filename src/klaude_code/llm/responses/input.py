# pyright: reportReturnType=false
# pyright: reportArgumentType=false

from typing import Any

from openai.types import responses

from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
)


def _build_user_content_parts(user: UserMessageItem) -> list[responses.ResponseInputContentParam]:
    parts: list[responses.ResponseInputContentParam] = []
    if user.content is not None:
        parts.append({"type": "input_text", "text": user.content})
    for image in user.images or []:
        parts.append({"type": "input_image", "detail": "auto", "image_url": image.image_url.url})
    if not parts:
        parts.append({"type": "input_text", "text": ""})
    return parts


def _build_tool_result_item(tool: ToolResultItem) -> responses.ResponseInputItemParam:
    content_parts: list[responses.ResponseInputContentParam] = []
    text_output = tool.output or ""
    if text_output:
        content_parts.append({"type": "input_text", "text": text_output})
    for image in tool.images or []:
        content_parts.append({"type": "input_image", "detail": "auto", "image_url": image.image_url.url})

    item: dict[str, Any] = {
        "type": "function_call_output",
        "call_id": tool.call_id,
        "output": content_parts,
    }
    return item  # type: ignore[return-value]


def convert_history_to_input(
    history: list[ConversationItem],
    model_name: str | None = None,
) -> responses.ResponseInputParam:
    """
    Convert a list of conversation items to a list of response input params.

    Args:
        history: List of conversation items.
        model_name: Model name. Used to verify that signatures are valid for the same model.
    """
    items: list[responses.ResponseInputItemParam] = []
    last_user_index: int | None = None
    # Preserve reasoning only from the most recent user turn to keep tool chains compact.

    for idx in range(len(history) - 1, -1, -1):
        if isinstance(history[idx], UserMessageItem):
            last_user_index = idx
            break

    pending_reasoning_text: str | None = None

    for index, item in enumerate(history):
        match item:
            case ReasoningTextItem() as item:
                # For now, we only store the text. We wait for the encrypted item to output both.
                # If no encrypted item follows (e.g. incomplete stream?), this text might be lost
                # or we can choose to output it if the next item is NOT reasoning?
                # For now, based on instructions, we pair them.
                if last_user_index is None or index >= last_user_index:
                    pending_reasoning_text = item.content

            case ReasoningEncryptedItem() as item:
                if (
                    (last_user_index is None or index >= last_user_index)
                    and item.encrypted_content
                    and len(item.encrypted_content) > 0
                    and model_name == item.model
                ):
                    items.append(convert_reasoning_inputs(pending_reasoning_text, item))
                # Reset pending text after consumption
                pending_reasoning_text = None

            case ToolCallItem() as t:
                items.append(
                    {
                        "type": "function_call",
                        "name": t.name,
                        "arguments": t.arguments,
                        "call_id": t.call_id,
                        "id": t.id,
                    }
                )
            case ToolResultItem() as t:
                items.append(_build_tool_result_item(t))
            case AssistantMessageItem() as a:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "id": a.id,
                        "content": [
                            {
                                "type": "output_text",
                                "text": a.content,
                            }
                        ],
                    }
                )
            case UserMessageItem() as u:
                items.append(
                    {
                        "type": "message",
                        "role": "user",
                        "id": u.id,
                        "content": _build_user_content_parts(u),
                    }
                )
            case DeveloperMessageItem() as d:
                dev_parts: list[responses.ResponseInputContentParam] = []
                if d.content is not None:
                    dev_parts.append({"type": "input_text", "text": d.content})
                for image in d.images or []:
                    dev_parts.append({"type": "input_image", "detail": "auto", "image_url": image.image_url.url})
                if not dev_parts:
                    dev_parts.append({"type": "input_text", "text": ""})
                items.append(
                    {
                        "type": "message",
                        "role": "user",  # GPT-5 series do not support image in "developer" role, so we set it to "user"
                        "id": d.id,
                        "content": dev_parts,
                    }
                )
            case _:
                # Other items may be Metadata
                continue

    return items


def convert_reasoning_inputs(
    text_content: str | None, encrypted_item: ReasoningEncryptedItem
) -> responses.ResponseInputItemParam:
    result = {"type": "reasoning", "content": None}

    if text_content is not None:
        result["summary"] = [
            {
                "type": "summary_text",
                "text": text_content,
            }
        ]
    if encrypted_item.encrypted_content:
        result["encrypted_content"] = encrypted_item.encrypted_content
    if encrypted_item.id is not None:
        result["id"] = encrypted_item.id
    return result


def convert_tool_schema(
    tools: list[ToolSchema] | None,
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
