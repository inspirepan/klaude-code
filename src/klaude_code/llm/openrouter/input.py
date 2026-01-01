# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
# pyright: reportUnnecessaryIsInstance=false
# pyright: reportGeneralTypeIssues=false

from openai.types import chat

from klaude_code.llm.image import assistant_image_to_data_url
from klaude_code.llm.input_common import DeveloperAttachment, attach_developer_messages, merge_reminder_text
from klaude_code.protocol import model


def is_claude_model(model_name: str | None) -> bool:
    """Return True if the model name represents an Anthropic Claude model."""

    return model_name is not None and model_name.startswith("anthropic/claude")


def is_gemini_model(model_name: str | None) -> bool:
    """Return True if the model name represents a Google Gemini model."""

    return model_name is not None and model_name.startswith("google/gemini")


def _text_parts(parts: list[model.Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, model.TextPart))


def _user_message_to_openrouter(
    message: model.UserMessage,
    attachment: DeveloperAttachment,
) -> chat.ChatCompletionMessageParam:
    parts: list[dict[str, object]] = []
    for part in message.parts:
        if isinstance(part, model.TextPart):
            parts.append({"type": "text", "text": part.text})
        elif isinstance(part, model.ImageURLPart):
            parts.append({"type": "image_url", "image_url": {"url": part.url}})
    if attachment.text:
        parts.append({"type": "text", "text": attachment.text})
    for image in attachment.images:
        parts.append({"type": "image_url", "image_url": {"url": image.url}})
    if not parts:
        parts.append({"type": "text", "text": ""})
    return {"role": "user", "content": parts}


def _tool_message_to_openrouter(
    message: model.ToolResultMessage,
    attachment: DeveloperAttachment,
) -> chat.ChatCompletionMessageParam:
    merged_text = merge_reminder_text(
        message.output_text or "<system-reminder>Tool ran without output or errors</system-reminder>",
        attachment.text,
    )
    return {
        "role": "tool",
        "content": [{"type": "text", "text": merged_text}],
        "tool_call_id": message.call_id,
    }


def _assistant_message_to_openrouter(
    message: model.AssistantMessage, model_name: str | None
) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}

    images = [part for part in message.parts if isinstance(part, model.ImageFilePart)]
    if images:
        assistant_message["images"] = [
            {
                "image_url": {
                    "url": assistant_image_to_data_url(image),
                }
            }
            for image in images
        ]

    tool_calls = [part for part in message.parts if isinstance(part, model.ToolCallPart)]
    if tool_calls:
        assistant_message["tool_calls"] = [
            {
                "id": tc.call_id,
                "type": "function",
                "function": {
                    "name": tc.tool_name,
                    "arguments": tc.arguments_json,
                },
            }
            for tc in tool_calls
        ]

    reasoning_details: list[dict[str, object]] = []
    degraded_thinking_texts: list[str] = []
    for part in message.parts:
        if isinstance(part, model.ThinkingTextPart):
            if part.model_id and model_name and part.model_id != model_name:
                degraded_thinking_texts.append(part.text)
                continue
            reasoning_details.append(
                {
                    "id": part.id,
                    "type": "reasoning.text",
                    "text": part.text,
                    "index": len(reasoning_details),
                }
            )
        elif isinstance(part, model.ThinkingSignaturePart):
            if part.model_id and model_name and part.model_id != model_name:
                continue
            if part.signature:
                reasoning_details.append(
                    {
                        "id": part.id,
                        "type": "reasoning.encrypted",
                        "data": part.signature,
                        "format": part.format,
                        "index": len(reasoning_details),
                    }
                )
    if reasoning_details:
        assistant_message["reasoning_details"] = reasoning_details

    content_parts: list[str] = []
    if degraded_thinking_texts:
        content_parts.append("<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>")
    text_content = _text_parts(message.parts)
    if text_content:
        content_parts.append(text_content)
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
    history: list[model.Message],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """Convert a list of messages to chat completion params."""
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

    for message, attachment in attach_developer_messages(history):
        match message:
            case model.SystemMessage():
                system_text = "\n".join(part.text for part in message.parts)
                if system_text:
                    if use_cache_control:
                        messages.append(
                            {
                                "role": "system",
                                "content": [
                                    {
                                        "type": "text",
                                        "text": system_text,
                                        "cache_control": {"type": "ephemeral"},
                                    }
                                ],
                            }
                        )
                    else:
                        messages.append({"role": "system", "content": system_text})
            case model.UserMessage():
                messages.append(_user_message_to_openrouter(message, attachment))
            case model.ToolResultMessage():
                messages.append(_tool_message_to_openrouter(message, attachment))
            case model.AssistantMessage():
                messages.append(_assistant_message_to_openrouter(message, model_name))
            case _:
                continue

    _add_cache_control(messages, use_cache_control)
    return messages
