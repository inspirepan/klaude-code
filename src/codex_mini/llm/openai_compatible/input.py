# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false


from collections.abc import Iterator
from typing import Iterable, Literal

from openai.types import chat

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessage,
    ReasoningItem,
    ResponseItem,
    ToolCallItem,
    ToolMessage,
    UserMessage,
)


def group_reponse_items_gen(
    items: Iterable[ResponseItem],
) -> Iterator[tuple[Literal["assistantish", "user", "tool"], list[ResponseItem]]]:
    """
    Group response items into sublists:
    - Consecutive (ReasoningItem | AssistantMessage | ToolCallItem) are grouped together
    - Consecutive UserMessage are grouped together
    - Each ToolMessage is always a single group
    """
    buffer: list[ResponseItem] = []
    buffer_kind: str | None = None  # 'assistantish' | 'user' | None

    def kind_of(it: ResponseItem) -> str:
        if isinstance(it, (ReasoningItem, AssistantMessage, ToolCallItem)):
            return "assistantish"
        if isinstance(it, UserMessage):
            return "user"
        if isinstance(it, ToolMessage):
            return "tool"
        return "other"

    for item in items:
        k = kind_of(item)

        if k == "tool":
            # ToolMessage: flush current buffer and yield as single group
            if buffer:
                yield (buffer_kind, buffer)
                buffer, buffer_kind = [], None
            yield ("tool", [item])
            continue

        if not buffer:
            buffer = [item]
            buffer_kind = k
        else:
            if k == buffer_kind:
                buffer.append(item)
            else:
                # Type switched, flush current buffer
                yield (buffer_kind, buffer)
                buffer = [item]
                buffer_kind = k

    if buffer:
        yield (buffer_kind, buffer)


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
                messages.append(
                    {
                        "role": "tool",
                        "content": [
                            {
                                "type": "text",
                                "text": item.content,
                            }
                            for item in group
                            if isinstance(item, ToolMessage)
                        ],
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
                            if "content" not in assistant_message:
                                assistant_message["content"] = []
                            assistant_message["content"].append(
                                {
                                    "type": "text",
                                    "text": assistant_message_item.content,
                                }
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

    return messages


def convert_tool_schema(
    tools: list[ToolSchema] | None,
) -> list[chat.ChatCompletionToolParam]:
    pass
