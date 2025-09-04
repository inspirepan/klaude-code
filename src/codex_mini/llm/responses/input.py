# pyright: reportReturnType=false
# pyright: reportArgumentType=false

from openai.types import responses

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessage,
    ReasoningItem,
    ResponseItem,
    ToolCallItem,
    ToolMessage,
    UserMessage,
)


def convert_history_to_input(
    history: list[ResponseItem],
) -> responses.ResponseInputParam:
    items: list[responses.ResponseInputItemParam] = []
    for item in history:
        match item:
            case ReasoningItem() as item:
                # items.append(convert_reasoning_item(item))
                pass
            case ToolCallItem() as tool_call_item:
                items.append(
                    {
                        "type": "function_call",
                        "name": tool_call_item.name,
                        "arguments": tool_call_item.arguments,
                        "call_id": tool_call_item.call_id,
                        "id": tool_call_item.id,
                    }
                )
            case ToolMessage() as tool_message_item:
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_message_item.call_id,
                        "output": tool_message_item.content,
                    }
                )
            case AssistantMessage() as assistant_message_item:
                items.append(
                    {
                        "type": "message",
                        "role": "assistant",
                        "id": assistant_message_item.id,
                        "content": [
                            {
                                "type": "output_text",
                                "text": assistant_message_item.content,
                            }
                        ],
                    }
                )
            case UserMessage() as user_message_item:
                items.append(
                    {
                        "type": "message",
                        "role": "user",
                        "id": user_message_item.id,
                        "content": [
                            {
                                "type": "input_text",
                                "text": user_message_item.content,
                            }
                        ],
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
