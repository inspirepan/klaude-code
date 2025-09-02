# pyright: reportReturnType=false
# pyright: reportArgumentType=false

from openai.types.responses import ResponseInputItemParam, ResponseInputParam, ToolParam

from src.protocal.llm_parameter import Tool
from src.protocal.model import (
    ContentPart,
    MessageItem,
    ReasoningItem,
    ResponseItem,
    ToolCallItem,
    ToolMessage,
)


def convert_history_to_input(history: list[ResponseItem]) -> ResponseInputParam:
    items: list[ResponseInputItemParam] = []
    for item in history:
        if isinstance(item, MessageItem):
            items.append(convert_message_item(item))
        elif isinstance(item, ReasoningItem):
            items.append(convert_reasoning_item(item))
        elif isinstance(item, ToolCallItem):
            items.append(convert_tool_call_item(item))
        else:
            # Other items may be Metadata
            continue

    return items


def convert_message_item(item: MessageItem) -> ResponseInputItemParam:
    if item.role == "tool" and isinstance(item, ToolMessage):
        return {
            "type": "function_call_output",
            "call_id": item.call_id,
            "output": "\n".join(
                [str(content_item.text) for content_item in item.content]
            ),
        }
    return {
        "type": "message",
        "role": item.role,
        "id": item.id,
        "content": [
            convert_content_item(content, item.role) for content in item.content
        ],
    }


def convert_reasoning_item(item: ReasoningItem) -> ResponseInputItemParam:
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


def convert_content_item(item: ContentPart, role: str) -> ResponseInputItemParam:
    if item.text is not None:
        return {
            "type": "output_text" if role == "assistant" else "input_text",
            "text": item.text,
        }
    raise ValueError("Non-text Content Not Supported")


def convert_tool_call_item(item: ToolCallItem) -> ResponseInputItemParam:
    return {
        "type": "function_call",
        "name": item.name,
        "arguments": item.arguments,
        "call_id": item.call_id,
        "id": item.id,
    }


def convert_tool_schema(tools: list[Tool] | None) -> list[ToolParam]:
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
