# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

import json
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Any

from google.genai import types

from klaude_code.llm.input_common import DeveloperAttachment, attach_developer_messages, merge_reminder_text
from klaude_code.protocol import llm_param, model


def _data_url_to_blob(url: str) -> types.Blob:
    header_and_media = url.split(",", 1)
    if len(header_and_media) != 2:
        raise ValueError("Invalid data URL for image: missing comma separator")
    header, base64_data = header_and_media
    if not header.startswith("data:"):
        raise ValueError("Invalid data URL for image: missing data: prefix")
    if ";base64" not in header:
        raise ValueError("Invalid data URL for image: missing base64 marker")

    media_type = header[5:].split(";", 1)[0]
    base64_payload = base64_data.strip()
    if base64_payload == "":
        raise ValueError("Inline image data is empty")

    try:
        decoded = b64decode(base64_payload, validate=True)
    except (BinasciiError, ValueError) as exc:
        raise ValueError("Inline image data is not valid base64") from exc

    return types.Blob(data=decoded, mime_type=media_type)


def _image_part_to_part(image: model.ImageURLPart) -> types.Part:
    url = image.url
    if url.startswith("data:"):
        return types.Part(inline_data=_data_url_to_blob(url))
    # Best-effort: Gemini supports file URIs, and may accept public HTTPS URLs.
    return types.Part(file_data=types.FileData(file_uri=url))


def _user_message_to_content(message: model.UserMessage, attachment: DeveloperAttachment) -> types.Content:
    parts: list[types.Part] = []
    for part in message.parts:
        if isinstance(part, model.TextPart):
            parts.append(types.Part(text=part.text))
        elif isinstance(part, model.ImageURLPart):
            parts.append(_image_part_to_part(part))
    if attachment.text:
        parts.append(types.Part(text=attachment.text))
    for image in attachment.images:
        parts.append(_image_part_to_part(image))
    if not parts:
        parts.append(types.Part(text=""))
    return types.Content(role="user", parts=parts)


def _tool_messages_to_contents(
    messages: list[tuple[model.ToolResultMessage, DeveloperAttachment]], model_name: str | None
) -> list[types.Content]:
    supports_multimodal_function_response = bool(model_name and "gemini-3" in model_name.lower())

    response_parts: list[types.Part] = []
    extra_image_contents: list[types.Content] = []

    for message, attachment in messages:
        merged_text = merge_reminder_text(
            message.output_text or "<system-reminder>Tool ran without output or errors</system-reminder>",
            attachment.text,
        )
        has_text = merged_text.strip() != ""

        images = [part for part in message.parts if isinstance(part, model.ImageURLPart)] + attachment.images
        image_parts: list[types.Part] = []
        for image in images:
            try:
                image_parts.append(_image_part_to_part(image))
            except ValueError:
                continue

        has_images = len(image_parts) > 0
        response_value = merged_text if has_text else "(see attached image)" if has_images else ""
        response_payload = {"error": response_value} if message.status != "success" else {"output": response_value}

        function_response = types.FunctionResponse(
            id=message.call_id,
            name=message.tool_name,
            response=response_payload,
            parts=image_parts if (has_images and supports_multimodal_function_response) else None,
        )
        response_parts.append(types.Part(function_response=function_response))

        if has_images and not supports_multimodal_function_response:
            extra_image_contents.append(
                types.Content(role="user", parts=[types.Part(text="Tool result image:"), *image_parts])
            )

    contents: list[types.Content] = []
    if response_parts:
        contents.append(types.Content(role="user", parts=response_parts))
    contents.extend(extra_image_contents)
    return contents


def _assistant_message_to_content(message: model.AssistantMessage, model_name: str | None) -> types.Content | None:
    parts: list[types.Part] = []

    degraded_thinking_texts: list[str] = []
    pending_thought_text: str | None = None
    pending_thought_signature: str | None = None

    def flush_thought() -> None:
        nonlocal pending_thought_text, pending_thought_signature
        if pending_thought_text is None:
            return
        parts.append(
            types.Part(
                text=pending_thought_text,
                thought=True,
                thought_signature=pending_thought_signature,
            )
        )
        pending_thought_text = None
        pending_thought_signature = None

    for part in message.parts:
        if isinstance(part, model.ThinkingTextPart):
            if part.model_id and model_name and part.model_id != model_name:
                degraded_thinking_texts.append(part.text)
                continue
            pending_thought_text = part.text
            continue
        if isinstance(part, model.ThinkingSignaturePart):
            if part.model_id and model_name and part.model_id != model_name:
                continue
            if part.signature and (part.format or "").startswith("google"):
                pending_thought_signature = part.signature
            continue

        flush_thought()
        if isinstance(part, model.TextPart):
            parts.append(types.Part(text=part.text))
        elif isinstance(part, model.ToolCallPart):
            args: dict[str, Any]
            if part.arguments_json:
                try:
                    args = json.loads(part.arguments_json)
                except json.JSONDecodeError:
                    args = {"_raw": part.arguments_json}
            else:
                args = {}
            parts.append(types.Part(function_call=types.FunctionCall(id=part.call_id, name=part.tool_name, args=args)))

    flush_thought()

    if degraded_thinking_texts:
        parts.insert(0, types.Part(text="<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"))

    if not parts:
        return None
    return types.Content(role="model", parts=parts)


def convert_history_to_contents(
    history: list[model.Message],
    model_name: str | None,
) -> list[types.Content]:
    contents: list[types.Content] = []
    pending_tool_messages: list[tuple[model.ToolResultMessage, DeveloperAttachment]] = []

    def flush_tool_messages() -> None:
        nonlocal pending_tool_messages
        if pending_tool_messages:
            contents.extend(_tool_messages_to_contents(pending_tool_messages, model_name=model_name))
            pending_tool_messages = []

    for message, attachment in attach_developer_messages(history):
        match message:
            case model.ToolResultMessage():
                pending_tool_messages.append((message, attachment))
            case model.UserMessage():
                flush_tool_messages()
                contents.append(_user_message_to_content(message, attachment))
            case model.AssistantMessage():
                flush_tool_messages()
                content = _assistant_message_to_content(message, model_name=model_name)
                if content is not None:
                    contents.append(content)
            case model.SystemMessage():
                continue
            case _:
                continue

    flush_tool_messages()
    return contents


def convert_tool_schema(tools: list[llm_param.ToolSchema] | None) -> list[types.Tool]:
    if tools is None or len(tools) == 0:
        return []
    declarations = [
        types.FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters_json_schema=tool.parameters,
        )
        for tool in tools
    ]
    return [types.Tool(function_declarations=declarations)]
