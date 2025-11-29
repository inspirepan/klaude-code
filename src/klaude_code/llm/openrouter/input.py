# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
# pyright: reportUnnecessaryIsInstance=false
# pyright: reportGeneralTypeIssues=false

from openai.types import chat
from openai.types.chat import ChatCompletionContentPartParam

from klaude_code.llm.input_common import AssistantGroup, ToolGroup, UserGroup, merge_reminder_text, parse_message_groups
from klaude_code.protocol import model


def is_claude_model(model_name: str | None):
    return model_name is not None and model_name.startswith("anthropic/claude")


def is_gemini_model(model_name: str | None):
    return model_name is not None and model_name.startswith("google/gemini")


def _user_group_to_message(group: UserGroup) -> chat.ChatCompletionMessageParam:
    parts: list[ChatCompletionContentPartParam] = []
    for text in group.text_parts:
        parts.append({"type": "text", "text": text + "\n"})
    for image in group.images:
        parts.append({"type": "image_url", "image_url": {"url": image.image_url.url}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return {"role": "user", "content": parts}


def _tool_group_to_message(group: ToolGroup) -> chat.ChatCompletionMessageParam:
    merged_text = merge_reminder_text(group.tool_result.output, group.reminder_texts)
    if not merged_text:
        merged_text = "<system-reminder>Tool ran without output or errors</system-reminder>"
    return {
        "role": "tool",
        "content": [{"type": "text", "text": merged_text}],
        "tool_call_id": group.tool_result.call_id,
    }


def _assistant_group_to_message(group: AssistantGroup, model_name: str | None) -> chat.ChatCompletionMessageParam:
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

    # Handle reasoning for OpenRouter (reasoning_details array).
    # The order of items in reasoning_details must match the original
    # stream order from the provider, so we iterate reasoning_items
    # instead of the separated reasoning_text / reasoning_encrypted lists.
    reasoning_details: list[dict[str, object]] = []
    for item in group.reasoning_items:
        if model_name != item.model:
            continue
        if isinstance(item, model.ReasoningEncryptedItem):
            if item.encrypted_content and len(item.encrypted_content) > 0:
                reasoning_details.append(
                    {
                        "id": item.id,
                        "type": "reasoning.encrypted",
                        "data": item.encrypted_content,
                        "format": item.format,
                        "index": len(reasoning_details),
                    }
                )
        elif isinstance(item, model.ReasoningTextItem):
            reasoning_details.append(
                {
                    "id": item.id,
                    "type": "reasoning.text",
                    "text": item.content,
                    "index": len(reasoning_details),
                }
            )
    if reasoning_details:
        assistant_message["reasoning_details"] = reasoning_details

    return assistant_message


def _add_cache_control(messages: list[chat.ChatCompletionMessageParam], use_cache_control: bool) -> None:
    if not use_cache_control or len(messages) == 0:
        return
    for msg in reversed(messages):
        role = msg.get("role")
        if role in ("user", "tool"):
            content = msg.get("content")
            if isinstance(content, list) and len(content) > 0:
                last_part = content[-1]
                if isinstance(last_part, dict) and last_part.get("type") == "text":
                    last_part["cache_control"] = {"type": "ephemeral"}
            break


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
        model_name: Model name. Used to verify that signatures are valid for the same model.
    """
    use_cache_control = is_claude_model(model_name) or is_gemini_model(model_name)

    messages: list[chat.ChatCompletionMessageParam] = (
        [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ]
        if system and use_cache_control
        else ([{"role": "system", "content": system}] if system else [])
    )

    for group in parse_message_groups(history):
        match group:
            case UserGroup():
                messages.append(_user_group_to_message(group))
            case ToolGroup():
                messages.append(_tool_group_to_message(group))
            case AssistantGroup():
                messages.append(_assistant_group_to_message(group, model_name))

    _add_cache_control(messages, use_cache_control)
    return messages
