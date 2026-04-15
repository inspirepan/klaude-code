# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false
# pyright: reportAssignmentType=false
# pyright: reportUnnecessaryIsInstance=false
# pyright: reportGeneralTypeIssues=false

from typing import cast

from openai.types import chat

from klaude_code.llm.input_common import (
    attach_developer_messages,
    build_assistant_common_fields,
    build_chat_content_parts,
    build_tool_message_for_chat_completions,
    collect_text_content,
    split_thinking_parts,
)
from klaude_code.prompts.system_prompt import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    split_system_prompt_for_cache,
    strip_system_prompt_boundary,
)
from klaude_code.protocol import message
from klaude_code.protocol.model_id import is_claude_model as is_claude_model
from klaude_code.protocol.model_id import is_glm_model as is_glm_model
from klaude_code.protocol.model_id import is_gpt5_model as is_gpt5_model
from klaude_code.protocol.model_id import is_xai_model as is_xai_model


def _assistant_message_to_openrouter(
    msg: message.AssistantMessage, model_name: str | None
) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}
    assistant_message.update(build_assistant_common_fields(msg))
    reasoning_details: list[dict[str, object]] = []
    native_thinking_parts, degraded_thinking_texts = split_thinking_parts(msg, model_name)
    for part in native_thinking_parts:
        if isinstance(part, message.ThinkingTextPart):
            if is_gpt5_model(model_name):
                detail: dict[str, object] = {
                    "id": part.id,
                    "type": "reasoning.summary",
                    "summary": part.text,
                    "format": "openai-responses-v1",
                    "index": len(reasoning_details),
                }
            else:
                detail: dict[str, object] = {
                    "id": part.id,
                    "type": "reasoning.text",
                    "text": part.text,
                    "index": len(reasoning_details),
                }
                if part.format:
                    detail["format"] = part.format
            reasoning_details.append(detail)
        elif isinstance(part, message.ThinkingSignaturePart) and part.signature:
            if is_claude_model(model_name):
                if len(reasoning_details) > 0:
                    reasoning_details[-1]["signature"] = part.signature
            else:
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


def _rewrite_tool_message_for_claude(tool_message: dict[str, object]) -> None:
    content = tool_message.get("content")
    if not isinstance(content, str):
        return
    tool_message["content"] = [{"type": "text", "text": content}]


def convert_history_to_input(
    history: list[message.Message],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """Convert a list of messages to chat completion params."""
    use_cache_control = is_claude_model(model_name)

    messages: list[chat.ChatCompletionMessageParam] = []
    has_explicit_system_cache_control = False

    def append_system_message(text: str, *, cache_control: bool) -> None:
        nonlocal has_explicit_system_cache_control
        if use_cache_control:
            block: dict[str, object] = {"type": "text", "text": text}
            if cache_control:
                block["cache_control"] = {"type": "ephemeral"}
                has_explicit_system_cache_control = True
            messages.append(
                cast(
                    chat.ChatCompletionMessageParam,
                    {
                        "role": "system",
                        "content": [block],
                    },
                )
            )
            return

        messages.append(cast(chat.ChatCompletionMessageParam, {"role": "system", "content": text}))

    static_system, dynamic_system = split_system_prompt_for_cache(system)
    has_boundary = bool(system and SYSTEM_PROMPT_DYNAMIC_BOUNDARY in system)
    if use_cache_control:
        if static_system:
            append_system_message(static_system, cache_control=False)
        if dynamic_system:
            append_system_message(dynamic_system, cache_control=True)
        elif system and not has_boundary:
            append_system_message(system, cache_control=True)
    else:
        flattened_system = strip_system_prompt_boundary(system)
        if flattened_system:
            append_system_message(flattened_system, cache_control=False)

    for msg, attachment in attach_developer_messages(history):
        match msg:
            case message.SystemMessage():
                system_text = "\n".join(part.text for part in msg.parts)
                if system_text:
                    append_system_message(system_text, cache_control=False)
            case message.UserMessage():
                parts = build_chat_content_parts(msg, attachment)
                messages.append(cast(chat.ChatCompletionMessageParam, {"role": "user", "content": parts}))
            case message.ToolResultMessage():
                tool_msg, user_msg = build_tool_message_for_chat_completions(msg, attachment)
                if use_cache_control:
                    _rewrite_tool_message_for_claude(tool_msg)
                messages.append(cast(chat.ChatCompletionMessageParam, tool_msg))
                if user_msg is not None:
                    messages.append(cast(chat.ChatCompletionMessageParam, user_msg))
            case message.AssistantMessage():
                messages.append(_assistant_message_to_openrouter(msg, model_name))
            case _:
                continue

    if use_cache_control and not has_explicit_system_cache_control:
        for msg in reversed(messages):
            if msg.get("role") != "system":
                continue
            content = msg.get("content")
            if isinstance(content, list) and len(content) > 0 and isinstance(content[-1], dict):
                content[-1]["cache_control"] = {"type": "ephemeral"}
                break

    _add_cache_control(messages, use_cache_control)
    return messages
