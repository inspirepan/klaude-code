"""Message conversion utilities for Antigravity Cloud Code Assist API."""

import json
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Any, TypedDict

from klaude_code.const import EMPTY_TOOL_OUTPUT_MESSAGE
from klaude_code.llm.image import assistant_image_to_data_url, image_file_to_data_url, parse_data_url
from klaude_code.llm.input_common import (
    DeveloperAttachment,
    ImagePart,
    attach_developer_messages,
    merge_reminder_text,
    split_thinking_parts,
)
from klaude_code.protocol import llm_param, message


class InlineData(TypedDict, total=False):
    mimeType: str
    data: str


class FunctionCall(TypedDict, total=False):
    id: str
    name: str
    args: dict[str, Any]


class FunctionResponse(TypedDict, total=False):
    id: str
    name: str
    response: dict[str, Any]
    parts: list[dict[str, Any]]


class Part(TypedDict, total=False):
    text: str
    thought: bool
    thoughtSignature: str
    inlineData: InlineData
    functionCall: FunctionCall
    functionResponse: FunctionResponse


class Content(TypedDict):
    role: str
    parts: list[Part]


class FunctionDeclaration(TypedDict, total=False):
    name: str
    description: str
    parameters: dict[str, Any]


class Tool(TypedDict):
    functionDeclarations: list[FunctionDeclaration]


def _data_url_to_inline_data(url: str) -> InlineData:
    """Convert data URL to inline_data dict."""
    media_type, _, decoded = parse_data_url(url)
    import base64

    return InlineData(mimeType=media_type, data=base64.b64encode(decoded).decode("ascii"))


def _image_part_to_part(image: ImagePart) -> Part:
    """Convert ImageURLPart or ImageFilePart to Part dict."""
    url = image_file_to_data_url(image) if isinstance(image, message.ImageFilePart) else image.url
    if url.startswith("data:"):
        return Part(inlineData=_data_url_to_inline_data(url))
    # For non-data URLs, best-effort using inline_data format
    return Part(text=f"[Image: {url}]")


def _user_message_to_content(msg: message.UserMessage, attachment: DeveloperAttachment) -> Content:
    """Convert UserMessage to Content dict."""
    parts: list[Part] = []
    for part in msg.parts:
        if isinstance(part, message.TextPart):
            parts.append(Part(text=part.text))
        elif isinstance(part, (message.ImageURLPart, message.ImageFilePart)):
            parts.append(_image_part_to_part(part))
    if attachment.text:
        parts.append(Part(text=attachment.text))
    for image in attachment.images:
        parts.append(_image_part_to_part(image))
    if not parts:
        parts.append(Part(text=""))
    return Content(role="user", parts=parts)


def _tool_messages_to_contents(
    msgs: list[tuple[message.ToolResultMessage, DeveloperAttachment]], model_name: str | None
) -> list[Content]:
    """Convert tool result messages to Content dicts."""
    supports_multimodal_function_response = bool(model_name and "gemini-3" in model_name.lower())

    response_parts: list[Part] = []
    extra_image_contents: list[Content] = []

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
        image_parts: list[Part] = []
        function_response_parts: list[dict[str, Any]] = []

        for image in images:
            try:
                image_parts.append(_image_part_to_part(image))
                if isinstance(image, message.ImageFilePart):
                    inline_data = _data_url_to_inline_data(image_file_to_data_url(image))
                    function_response_parts.append({"inlineData": inline_data})
                elif image.url.startswith("data:"):
                    inline_data = _data_url_to_inline_data(image.url)
                    function_response_parts.append({"inlineData": inline_data})
            except ValueError:
                continue

        has_images = len(image_parts) > 0
        response_value = merged_text if has_text else "(see attached image)" if has_images else ""
        response_payload = {"error": response_value} if msg.status != "success" else {"output": response_value}

        function_response = FunctionResponse(
            id=msg.call_id,
            name=msg.tool_name,
            response=response_payload,
        )
        if has_images and supports_multimodal_function_response:
            function_response["parts"] = function_response_parts

        response_parts.append(Part(functionResponse=function_response))

        if has_images and not supports_multimodal_function_response:
            extra_image_contents.append(Content(role="user", parts=[Part(text="Tool result image:"), *image_parts]))

    contents: list[Content] = []
    if response_parts:
        contents.append(Content(role="user", parts=response_parts))
    contents.extend(extra_image_contents)
    return contents


def _decode_thought_signature(sig: str | None) -> str | None:
    """Validate base64 thought signature."""
    if not sig:
        return None
    try:
        b64decode(sig)
        return sig
    except (BinasciiError, ValueError):
        return None


def _assistant_message_to_content(msg: message.AssistantMessage, model_name: str | None) -> Content | None:
    """Convert AssistantMessage to Content dict."""
    parts: list[Part] = []
    native_thinking_parts, degraded_thinking_texts = split_thinking_parts(msg, model_name)
    native_thinking_ids = {id(part) for part in native_thinking_parts}

    for part in msg.parts:
        if isinstance(part, message.ThinkingTextPart):
            if id(part) not in native_thinking_ids:
                continue
            parts.append(Part(text=part.text, thought=True))

        elif isinstance(part, message.ThinkingSignaturePart):
            if id(part) not in native_thinking_ids:
                continue
            if not part.signature or part.format != "google":
                continue
            # Attach signature to the previous part
            if parts:
                sig = _decode_thought_signature(part.signature)
                if sig:
                    parts[-1]["thoughtSignature"] = sig

        elif isinstance(part, message.TextPart):
            # Skip empty text blocks
            if not part.text or part.text.strip() == "":
                continue
            parts.append(Part(text=part.text))

        elif isinstance(part, message.ToolCallPart):
            args: dict[str, Any]
            if part.arguments_json:
                try:
                    args = json.loads(part.arguments_json)
                except json.JSONDecodeError:
                    args = {"_raw": part.arguments_json}
            else:
                args = {}
            parts.append(Part(functionCall=FunctionCall(id=part.call_id, name=part.tool_name, args=args)))

        elif isinstance(part, message.ImageFilePart):
            try:
                data_url = assistant_image_to_data_url(part)
                parts.append(_image_part_to_part(message.ImageURLPart(url=data_url)))
            except (ValueError, FileNotFoundError):
                pass

    if degraded_thinking_texts:
        parts.insert(0, Part(text="<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"))

    if not parts:
        return None
    return Content(role="model", parts=parts)


def convert_history_to_contents(
    history: list[message.Message],
    model_name: str | None,
) -> list[Content]:
    """Convert message history to Cloud Code Assist Content format."""
    contents: list[Content] = []
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


def convert_tool_schema(tools: list[llm_param.ToolSchema] | None) -> list[Tool] | None:
    """Convert tool schemas to Cloud Code Assist Tool format."""
    if tools is None or len(tools) == 0:
        return None
    declarations = [
        FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters=dict(tool.parameters) if tool.parameters else {},
        )
        for tool in tools
    ]
    return [Tool(functionDeclarations=declarations)]
