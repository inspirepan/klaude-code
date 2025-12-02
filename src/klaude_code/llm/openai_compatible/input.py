# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat
from openai.types.chat import ChatCompletionContentPartParam

from klaude_code.llm.input_common import AssistantGroup, ToolGroup, UserGroup, merge_reminder_text, parse_message_groups
from klaude_code.protocol import llm_param, model


def user_group_to_openai_message(group: UserGroup) -> chat.ChatCompletionMessageParam:
    """Convert a UserGroup to an OpenAI-compatible chat message."""
    parts: list[ChatCompletionContentPartParam] = []
    for text in group.text_parts:
        parts.append({"type": "text", "text": text + "\n"})
    for image in group.images:
        parts.append({"type": "image_url", "image_url": {"url": image.image_url.url}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return {"role": "user", "content": parts}


def tool_group_to_openai_message(group: ToolGroup) -> chat.ChatCompletionMessageParam:
    """Convert a ToolGroup to an OpenAI-compatible chat message."""
    merged_text = merge_reminder_text(
        group.tool_result.output or "<system-reminder>Tool ran without output or errors</system-reminder>",
        group.reminder_texts,
    )
    return {
        "role": "tool",
        "content": [{"type": "text", "text": merged_text}],
        "tool_call_id": group.tool_result.call_id,
    }


def _assistant_group_to_message(
    group: AssistantGroup,
) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}

    if group.text_content:
        assistant_message["content"] = group.text_content

    if group.tool_calls:
        assistant_message["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.name,
                    "arguments": tc.arguments,
                },
            }
            for tc in group.tool_calls
        ]

    return assistant_message


def build_user_content_parts(
    images: list[model.ImageURLPart],
) -> list[ChatCompletionContentPartParam]:
    """Build content parts for images only. Used by OpenRouter."""
    return [{"type": "image_url", "image_url": {"url": image.image_url.url}} for image in images]


def convert_history_to_input(
    history: list[model.ConversationItem],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """
    Convert a list of conversation items to a list of chat completion message params.

    Args:
        history: List of conversation items.
        system: System message.
        model_name: Model name. Not used in OpenAI-compatible, kept for API consistency.
    """
    messages: list[chat.ChatCompletionMessageParam] = [{"role": "system", "content": system}] if system else []

    for group in parse_message_groups(history):
        match group:
            case UserGroup():
                messages.append(user_group_to_openai_message(group))
            case ToolGroup():
                messages.append(tool_group_to_openai_message(group))
            case AssistantGroup():
                messages.append(_assistant_group_to_message(group))

    return messages


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
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
