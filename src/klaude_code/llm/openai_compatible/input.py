# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

from openai.types import chat
from openai.types.chat import ChatCompletionContentPartParam

from klaude_code.llm.image import assistant_image_to_data_url
from klaude_code.llm.input_common import DeveloperAttachment, attach_developer_messages, merge_reminder_text
from klaude_code.protocol import llm_param, model


def _text_parts(parts: list[model.Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, model.TextPart))


def _user_message_to_openai(
    message: model.UserMessage,
    attachment: DeveloperAttachment,
) -> chat.ChatCompletionMessageParam:
    parts: list[ChatCompletionContentPartParam] = []
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


def _tool_message_to_openai(
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


def _assistant_message_to_openai(message: model.AssistantMessage) -> chat.ChatCompletionMessageParam:
    assistant_message: dict[str, object] = {"role": "assistant"}

    text_content = _text_parts(message.parts)
    if text_content:
        assistant_message["content"] = text_content

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

    return assistant_message


def build_user_content_parts(
    images: list[model.ImageURLPart],
) -> list[ChatCompletionContentPartParam]:
    """Build content parts for images only. Used by OpenRouter."""
    return [{"type": "image_url", "image_url": {"url": image.url}} for image in images]


def convert_history_to_input(
    history: list[model.Message],
    system: str | None = None,
    model_name: str | None = None,
) -> list[chat.ChatCompletionMessageParam]:
    """Convert a list of messages to chat completion params."""
    del model_name
    messages: list[chat.ChatCompletionMessageParam] = [{"role": "system", "content": system}] if system else []

    for message, attachment in attach_developer_messages(history):
        match message:
            case model.SystemMessage():
                system_text = "\n".join(part.text for part in message.parts)
                if system_text:
                    messages.append({"role": "system", "content": system_text})
            case model.UserMessage():
                messages.append(_user_message_to_openai(message, attachment))
            case model.ToolResultMessage():
                messages.append(_tool_message_to_openai(message, attachment))
            case model.AssistantMessage():
                messages.append(_assistant_message_to_openai(message))
            case _:
                continue

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
