# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
# pyright: reportUnnecessaryIsInstance=false
# pyright: reportGeneralTypeIssues=false

from openai.types import chat

from klaude_code.llm.input_common import AssistantGroup, ToolGroup, UserGroup, parse_message_groups
from klaude_code.llm.openai_compatible.input import tool_group_to_openai_message, user_group_to_openai_message
from klaude_code.protocol import model


def is_claude_model(model_name: str | None) -> bool:
    """Return True if the model name represents an Anthropic Claude model."""

    return model_name is not None and model_name.startswith("anthropic/claude")


def is_gemini_model(model_name: str | None) -> bool:
    """Return True if the model name represents a Google Gemini model."""

    return model_name is not None and model_name.startswith("google/gemini")


def _assistant_group_to_message(group: AssistantGroup, model_name: str | None) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}

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
    # For cross-model scenarios, degrade thinking to plain text.
    reasoning_details: list[dict[str, object]] = []
    degraded_thinking_texts: list[str] = []
    for item in group.reasoning_items:
        if model_name != item.model:
            # Cross-model: collect thinking text for degradation
            if isinstance(item, model.ReasoningTextItem) and item.content:
                degraded_thinking_texts.append(item.content)
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

    # Build content with optional degraded thinking prefix
    content_parts: list[str] = []
    if degraded_thinking_texts:
        content_parts.append("<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>")
    if group.text_content:
        content_parts.append(group.text_content)
    if content_parts:
        assistant_message["content"] = "\n".join(content_parts)

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
                messages.append(user_group_to_openai_message(group))
            case ToolGroup():
                messages.append(tool_group_to_openai_message(group))
            case AssistantGroup():
                messages.append(_assistant_group_to_message(group, model_name))

    _add_cache_control(messages, use_cache_control)
    return messages
