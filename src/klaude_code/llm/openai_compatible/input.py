# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from typing import cast

from openai.types import chat

from klaude_code.llm.image import assistant_image_to_data_url
from klaude_code.llm.input_common import (
    attach_developer_messages,
    build_assistant_common_fields,
    build_chat_content_parts,
    build_tool_message,
    collect_text_content,
)
from klaude_code.protocol import llm_param, message


def _assistant_message_to_openai(msg: message.AssistantMessage) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}

    text_content = collect_text_content(msg.parts)
    if text_content:
        assistant_message["content"] = text_content

    assistant_message.update(build_assistant_common_fields(msg, image_to_data_url=assistant_image_to_data_url))
    return cast(chat.ChatCompletionMessageParam, assistant_message)


def convert_history_to_input(
    history: list[message.Message],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """Convert a list of messages to chat completion params."""
    del model_name
    messages: list[chat.ChatCompletionMessageParam] = (
        [cast(chat.ChatCompletionMessageParam, {"role": "system", "content": system})] if system else []
    )

    for msg, attachment in attach_developer_messages(history):
        match msg:
            case message.SystemMessage():
                system_text = "\n".join(part.text for part in msg.parts)
                if system_text:
                    messages.append(cast(chat.ChatCompletionMessageParam, {"role": "system", "content": system_text}))
            case message.UserMessage():
                parts = build_chat_content_parts(msg, attachment)
                messages.append(cast(chat.ChatCompletionMessageParam, {"role": "user", "content": parts}))
            case message.ToolResultMessage():
                messages.append(cast(chat.ChatCompletionMessageParam, build_tool_message(msg, attachment)))
            case message.AssistantMessage():
                messages.append(_assistant_message_to_openai(msg))
            case _:
                continue

    return messages


def convert_tool_schema(
    tools: list[llm_param.ToolSchema] | None,
) -> list[chat.ChatCompletionToolParam]:
    if tools is None:
        return []
    return [
        cast(
            chat.ChatCompletionToolParam,
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            },
        )
        for tool in tools
    ]
