# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

import json
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Any, cast

from google.genai import types

from klaude_code.const import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.llm.image import assistant_image_to_data_url, image_file_to_data_url, parse_data_url
from klaude_code.llm.input_common import (
    DeveloperAttachment,
    ImagePart,
    attach_developer_messages,
    merge_reminder_text,
    split_thinking_parts,
)
from klaude_code.llm.json_stable import canonicalize_json
from klaude_code.protocol import llm_param, message


def _data_url_to_blob(url: str) -> types.Blob:
    media_type, _, decoded = parse_data_url(url)
    return types.Blob(data=decoded, mime_type=media_type)


def _image_part_to_part(image: ImagePart) -> types.Part:
    url = image_file_to_data_url(image) if isinstance(image, message.ImageFilePart) else image.url
    if url.startswith("data:"):
        return types.Part(inline_data=_data_url_to_blob(url))
    # Best-effort: Gemini supports file URIs, and may accept public HTTPS URLs.
    return types.Part(file_data=types.FileData(file_uri=url))


def _image_part_to_function_response_part(image: ImagePart) -> types.FunctionResponsePart:
    url = image_file_to_data_url(image) if isinstance(image, message.ImageFilePart) else image.url
    if url.startswith("data:"):
        media_type, _, decoded = parse_data_url(url)
        return types.FunctionResponsePart.from_bytes(data=decoded, mime_type=media_type)
    return types.FunctionResponsePart.from_uri(file_uri=url)


def _user_message_to_content(msg: message.UserMessage, attachment: DeveloperAttachment) -> types.Content:
    parts: list[types.Part] = []
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            parts.append(types.Part(text=part.text))
        elif isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
            parts.append(_image_part_to_part(part))
    if attachment.text:
        parts.append(types.Part(text=attachment.text))
    for image in attachment.images:
        parts.append(_image_part_to_part(image))
    if not parts:
        parts.append(types.Part(text=""))
    return types.Content(role="user", parts=parts)


def _tool_messages_to_contents(
    msgs: list[tuple[message.ToolResultMessage, DeveloperAttachment]], model_name: str | None
) -> list[types.Content]:
    supports_multimodal_function_response = bool(model_name and "gemini-3" in model_name.lower())

    response_parts: list[types.Part] = []
    extra_image_contents: list[types.Content] = []

    for msg, attachment in msgs:
        merged_text = merge_reminder_text(
            msg.output_text or EMPTY_TOOL_OUTPUT_MESSAGE,
            attachment.text,
        )
        has_text = merged_text.strip() != ""

        images: list[ImagePart] = [
            part for part in msg.parts if isinstance(part, (message.ImageURLPart, message.ImageFilePart))
        ]
        images.extend(attachment.images)
        image_parts: list[types.Part] = []
        function_response_parts: list[types.FunctionResponsePart] = []

        for image in images:
            try:
                image_parts.append(_image_part_to_part(image))
                function_response_parts.append(_image_part_to_function_response_part(image))
            except ValueError:
                continue

        has_images = len(image_parts) > 0
        response_value = merged_text if has_text else "(see attached image)" if has_images else ""
        response_payload = {"error": response_value} if msg.status != "success" else {"output": response_value}

        function_response = types.FunctionResponse(
            id=msg.call_id,
            name=msg.tool_name,
            response=response_payload,
            parts=function_response_parts if (has_images and supports_multimodal_function_response) else None,
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


def _decode_thought_signature(sig: str | None) -> bytes | None:
    """Decode base64 thought signature to bytes."""
    if not sig:
        return None
    try:
        return b64decode(sig)
    except (BinasciiError, ValueError):
        return None


def _assistant_message_to_content(msg: message.AssistantMessage, model_name: str | None) -> types.Content | None:
    parts: list[types.Part] = []
    native_thinking_parts, degraded_thinking_texts = split_thinking_parts(msg, model_name)
    native_thinking_ids = {id(part) for part in native_thinking_parts}

    for part in msg.parts:
        if isinstance(part, message.ThinkingTextPart):
            if id(part) not in native_thinking_ids:
                continue
            parts.append(types.Part(text=part.text, thought=True))

        elif isinstance(part, message.ThinkingSignaturePart):
            if id(part) not in native_thinking_ids:
                continue
            if not part.signature or part.format != "google":
                continue
            # Attach signature to the previous part
            if parts:
                sig_bytes = _decode_thought_signature(part.signature)
                if sig_bytes:
                    last_part = parts[-1]
                    parts[-1] = types.Part(
                        text=last_part.text,
                        thought=last_part.thought,
                        function_call=last_part.function_call,
                        inline_data=last_part.inline_data,
                        file_data=last_part.file_data,
                        thought_signature=sig_bytes,
                    )

        elif isinstance(part, message.TextPart):
            parts.append(types.Part(text=part.text))

        elif isinstance(part, message.ToolCallPart):
            args: dict[str, Any]
            if part.arguments_json:
                try:
                    loaded: object = json.loads(part.arguments_json)
                except json.JSONDecodeError:
                    loaded = {"_raw": part.arguments_json}
            else:
                loaded = {}

            canonical = canonicalize_json(loaded)
            args = cast(dict[str, Any], canonical) if isinstance(canonical, dict) else {"_value": canonical}
            parts.append(
                types.Part(
                    function_call=types.FunctionCall(id=part.call_id, name=part.tool_name, args=args),
                )
            )

        elif isinstance(part, message.ImageFilePart):
            # Convert saved image back to inline_data for multi-turn
            try:
                data_url = assistant_image_to_data_url(part)
                parts.append(_image_part_to_part(message.ImageURLPart(url=data_url)))
            except (ValueError, FileNotFoundError):
                pass  # Skip if image cannot be loaded

    if degraded_thinking_texts:
        parts.insert(0, types.Part(text="<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"))

    if not parts:
        return None
    return types.Content(role="model", parts=parts)


def convert_history_to_contents(
    history: list[message.Message],
    model_name: str | None,
) -> list[types.Content]:
    contents: list[types.Content] = []
    pending_tool_messages: list[tuple[message.ToolResultMessage, DeveloperAttachment]] = []

    def flush_tool_messages() -> None:
        nonlocal pending_tool_messages
        if pending_tool_messages:
            contents.extend(_tool_messages_to_contents(pending_tool_messages, model_name=model_name))
            pending_tool_messages = []

    for msg, attachment in attach_developer_messages(history):
        match msg:
            case message.ToolResultMessage():
                pending_tool_messages.append((msg, attachment))
            case message.UserMessage():
                flush_tool_messages()
                contents.append(_user_message_to_content(msg, attachment))
            case message.AssistantMessage():
                flush_tool_messages()
                content = _assistant_message_to_content(msg, model_name=model_name)
                if content is not None:
                    contents.append(content)
            case message.SystemMessage():
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
            parameters_json_schema=canonicalize_json(tool.parameters),
        )
        for tool in tools
    ]
    return [types.Tool(function_declarations=declarations)]
