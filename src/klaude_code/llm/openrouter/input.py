# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
# pyright: reportUnnecessaryIsInstance=false
# pyright: reportGeneralTypeIssues=false

from typing import cast

from openai.types import chat

from klaude_code.llm.image import assistant_image_to_data_url
from klaude_code.llm.input_common import (
    attach_developer_messages,
    build_assistant_common_fields,
    build_chat_content_parts,
    build_tool_message,
    collect_text_content,
    split_thinking_parts,
)
from klaude_code.protocol import message


def is_claude_model(model_name: str | None) -> bool:
    """Return True if the model name represents an Anthropic Claude model."""

    return model_name is not None and model_name.startswith("anthropic/claude")


def is_gemini_model(model_name: str | None) -> bool:
    """Return True if the model name represents a Google Gemini model."""

    return model_name is not None and model_name.startswith("google/gemini")


def _assistant_message_to_openrouter(
    msg: message.AssistantMessage, model_name: str | None
) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}
    assistant_message.update(build_assistant_common_fields(msg, image_to_data_url=assistant_image_to_data_url))
    reasoning_details: list[dict[str, object]] = []
    native_thinking_parts, degraded_thinking_texts = split_thinking_parts(msg, model_name)
    for part in native_thinking_parts:
        if isinstance(part, message.ThinkingTextPart):
            reasoning_details.append(
                {
                    "id": part.id,
                    "type": "reasoning.text",
                    "text": part.text,
                    "index": len(reasoning_details),
                }
            )
        elif isinstance(part, message.ThinkingSignaturePart) and part.signature:
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
    text_content = collect_text_content(msg.parts)
    if text_content:
        content_parts.append(text_content)
    if content_parts:
        assistant_message["content"] = "\n".join(content_parts)

    return cast(chat.ChatCompletionMessageParam, assistant_message)


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
    history: list[message.Message],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """Convert a list of messages to chat completion params."""
    use_cache_control = is_claude_model(model_name) or is_gemini_model(model_name)

    messages: list[chat.ChatCompletionMessageParam] = (
        [
            cast(
                chat.ChatCompletionMessageParam,
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "text",
                            "text": system,
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                },
            )
        ]
        if system and use_cache_control
        else ([cast(chat.ChatCompletionMessageParam, {"role": "system", "content": system})] if system else [])
    )

    for msg, attachment in attach_developer_messages(history):
        match msg:
            case message.SystemMessage():
                system_text = "\n".join(part.text for part in msg.parts)
                if system_text:
                    if use_cache_control:
                        messages.append(
                            cast(
                                chat.ChatCompletionMessageParam,
                                {
                                    "role": "system",
                                    "content": [
                                        {
                                            "type": "text",
                                            "text": system_text,
                                            "cache_control": {"type": "ephemeral"},
                                        }
                                    ],
                                },
                            )
                        )
                    else:
                        messages.append(
                            cast(chat.ChatCompletionMessageParam, {"role": "system", "content": system_text})
                        )
            case message.UserMessage():
                parts = build_chat_content_parts(msg, attachment)
                messages.append(cast(chat.ChatCompletionMessageParam, {"role": "user", "content": parts}))
            case message.ToolResultMessage():
                messages.append(cast(chat.ChatCompletionMessageParam, build_tool_message(msg, attachment)))
            case message.AssistantMessage():
                messages.append(_assistant_message_to_openrouter(msg, model_name))
            case _:
                continue

    _add_cache_control(messages, use_cache_control)
    return messages
