# pyright: reportReturnType=false
# pyright: reportArgumentType=false

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
    for item in history:
        match item:
            case ReasoningItem() as item:
                if item.encrypted_content and len(item.encrypted_content) > 0 and model_name == item.model:
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
                items.append(
                    {
                        "type": "function_call_output",
                        "call_id": t.call_id,
                        "output": t.output,
                    }
                )
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
                        "content": [
                            {
                                "type": "input_text",
                                "text": u.content,
                            }
                        ],
                    }
                )
            case DeveloperMessageItem() as d:
                items.append(
                    {
                        "type": "message",
                        "role": "developer",
                        "id": d.id,
                        "content": [
                            {
                                "type": "input_text",
                                "text": d.content,
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
