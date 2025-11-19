# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat

from codex_mini.llm.openai_compatible.input import build_user_content_parts
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import (
    AssistantMessageItem,
    ConversationItem,
    DeveloperMessageItem,
    ReasoningEncryptedItem,
    ReasoningTextItem,
    ToolCallItem,
    ToolResultItem,
    group_response_items_gen,
)


def is_claude_model(model_name: str | None):
    return model_name is not None and model_name.startswith("anthropic/claude")


def is_complete_chunk_reasoning_model(model_name: str | None) -> bool:
    """
    Check if the model returns reasoning in complete chunks (like Gemini)
    rather than token-by-token streams.
    These models often include excessive newlines that should be trimmed.
    """
    return model_name is not None and model_name.startswith("google/gemini")


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
                        case ReasoningEncryptedItem() as r:
                            if model_name != r.model:
                                continue
                            if r.encrypted_content and len(r.encrypted_content) > 0:
                                if "reasoning_details" not in assistant_message:
                                    assistant_message["reasoning_details"] = []
                                assistant_message["reasoning_details"].append(
                                    {
                                        "id": r.id,
                                        "type": "reasoning.encrypted",
                                        "data": r.encrypted_content,
                                        "format": r.format,
                                        "index": 0,
                                    }
                                )
                        case ReasoningTextItem() as r:
                            if "reasoning_details" not in assistant_message:
                                assistant_message["reasoning_details"] = []
                            assistant_message["reasoning_details"].append(
                                {
                                    "id": r.id,
                                    "type": "reasoning.text",
                                    "text": r.content,
                                    "index": 0,  # TODO: index
                                }
                            )
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
