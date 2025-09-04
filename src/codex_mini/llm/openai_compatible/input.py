# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessage,
    ResponseItem,
    ToolCallItem,
    ToolMessage,
    UserMessage,
    group_reponse_items_gen,
)


def convert_history_to_input(
    history: list[ResponseItem],
    system: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    messages: list[chat.ChatCompletionMessageParam] = (
        [
            {
                "role": "system",
                "content": system,
            }
        ]
        if system
        else []
    )

    for group_kind, group in group_reponse_items_gen(history):
        match group_kind:
            case "user":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": item.content,
                            }
                            for item in group
                            if isinstance(item, UserMessage)
                        ],
                    }
                )
            case "tool":
                if len(group) == 0 or not isinstance(group[0], ToolMessage):
                    continue
                tool_message = group[0]
                messages.append(
                    {
                        "role": "tool",
                        "content": [
                            {
                                "type": "text",
                                "text": tool_message.content,
                            }
                        ],
                        "tool_call_id": tool_message.call_id,
                    }
                )
            case "assistantish":
                # Merge all items into a single assistant message
                assistant_message = {
                    "role": "assistant",
                }

                for item in group:
                    match item:
                        case AssistantMessage() as assistant_message_item:
                            if assistant_message_item.content:
                                if "content" not in assistant_message:
                                    assistant_message["content"] = (
                                        assistant_message_item.content
                                    )
                                else:
                                    assistant_message["content"] += (
                                        assistant_message_item.content
                                    )
                        case ToolCallItem() as tool_call_item:
                            if "tool_calls" not in assistant_message:
                                assistant_message["tool_calls"] = []
                            assistant_message["tool_calls"].append(
                                {
                                    "id": tool_call_item.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": tool_call_item.name,
                                        "arguments": tool_call_item.arguments,
                                    },
                                }
                            )
                        case _:
                            # Ignore reasoning
                            pass

                messages.append(assistant_message)
            case "other":
                pass

    return messages


def convert_tool_schema(
    tools: list[ToolSchema] | None,
) -> list[chat.ChatCompletionToolParam]:
    if tools is None:
        return []
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
            },
        }
        for tool in tools
    ]
