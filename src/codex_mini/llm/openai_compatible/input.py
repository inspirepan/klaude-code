# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
    group_response_items_gen,
)


def convert_history_to_input(
    history: list[ConversationItem],
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

    for group_kind, group in group_response_items_gen(history):
        match group_kind:
            case "user":
                messages.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": item.content + "\n",
                            }
                            for item in group
                            if isinstance(item, (UserMessageItem, DeveloperMessageItem)) and item.content is not None
                        ],
                    }
                )
            case "tool":
                if len(group) == 0 or not isinstance(group[0], ToolResultItem):
                    continue
                tool_result = group[0]
                reminders: list[DeveloperMessageItem] = [i for i in group if isinstance(i, DeveloperMessageItem)]
                reminders_str = "\n" + "\n".join(i.content for i in reminders if i.content)
                messages.append(
                    {
                        "role": "tool",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    tool_result.output
                                    or "<system-reminder>Tool ran without output or errors</system-reminder>"
                                )
                                + reminders_str,
                            }
                        ],
                        "tool_call_id": tool_result.call_id,
                    }
                )
            case "assistant":
                # Merge all items into a single assistant message
                assistant_message = {
                    "role": "assistant",
                }

                for item in group:
                    match item:
                        case AssistantMessageItem() as a:
                            if a.content:
                                if "content" not in assistant_message:
                                    assistant_message["content"] = a.content
                                else:
                                    assistant_message["content"] += a.content
                        case ToolCallItem() as t:
                            if "tool_calls" not in assistant_message:
                                assistant_message["tool_calls"] = []
                            assistant_message["tool_calls"].append(
                                {
                                    "id": t.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": t.name,
                                        "arguments": t.arguments,
                                    },
                                }
                            )
                        case ReasoningItem() as r:
                            if r.encrypted_content and len(r.encrypted_content) > 0:
                                # https://openrouter.ai/docs/use-cases/reasoning-tokens#advanced-usage-reasoning-chain-of-thought
                                assistant_message["reasoning_details"] = [
                                    {
                                        "id": r.id,
                                        "type": "reasoning.encrypted",
                                        "data": r.encrypted_content,
                                        "format": r.format,
                                        "index": 0,
                                    }
                                ]

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
