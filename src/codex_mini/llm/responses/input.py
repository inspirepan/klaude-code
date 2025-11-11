# pyright: reportReturnType=false
# pyright: reportArgumentType=false

from typing import Any

from openai.types import responses

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningItem,
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
        "output": text_output,
    }
    if content_parts:
        item["content"] = content_parts
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

    for index, item in enumerate(history):
        match item:
            case ReasoningItem() as item:
                if (
                    (last_user_index is None or index >= last_user_index)
                    and item.encrypted_content
                    and len(item.encrypted_content) > 0
                    and model_name == item.model
                ):
                    items.append(convert_reasoning_item(item))
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


def convert_reasoning_item(item: ReasoningItem) -> responses.ResponseInputItemParam:
    result = {"type": "reasoning", "content": None}

    if item.summary is not None:
        result["summary"] = [
            {
                "type": "summary_text",
                "text": summary_item,
            }
            for summary_item in item.summary
        ]
    if item.encrypted_content is not None:
        result["encrypted_content"] = item.encrypted_content
    if item.id is not None:
        result["id"] = item.id
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
