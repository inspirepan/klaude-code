# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat
from openai.types.chat import ChatCompletionContentPartParam

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ToolCallItem,
    ToolResultItem,
    UserMessageItem,
    group_response_items_gen,
)


def build_user_content_parts(group: list[ConversationItem]) -> list[ChatCompletionContentPartParam]:
    parts: list[ChatCompletionContentPartParam] = []
    for item in group:
        if isinstance(item, (UserMessageItem, DeveloperMessageItem)):
            if item.content is not None:
                parts.append({"type": "text", "text": item.content + "\n"})
            for image in item.images or []:
                parts.append({"type": "image_url", "image_url": {"url": image.image_url.url}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return parts


def convert_history_to_input(
    history: list[ConversationItem],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """
    Convert a list of conversation items to a list of chat completion message params.

    Args:
        history: List of conversation items.
        system: System message.
        model_name: Model name. Used to verify that signatures are valid for the same model.
    """
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
                messages.append({"role": "user", "content": build_user_content_parts(group)})
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
                        case ReasoningTextItem() | ReasoningEncryptedItem():
                            continue  # Skip reasoning items in OpenAICompatible assistant message
                        case _:
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
