# pyright: reportReturnType=false
# pyright: reportArgumentType=false
# pyright: reportUnknownMemberType=false
# pyright: reportAttributeAccessIssue=false

import json
from base64 import b64decode
from binascii import Error as BinasciiError
from typing import Any

from google.genai import types

from klaude_code.llm.input_common import AssistantGroup, ToolGroup, UserGroup, merge_reminder_text, parse_message_groups
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
    url = image.image_url.url
    if url.startswith("data:"):
        return types.Part(inline_data=_data_url_to_blob(url))
    # Best-effort: Gemini supports file URIs, and may accept public HTTPS URLs.
    return types.Part(file_data=types.FileData(file_uri=url))


def _user_group_to_content(group: UserGroup) -> types.Content:
    parts: list[types.Part] = []
    for text in group.text_parts:
        parts.append(types.Part(text=text + "\n"))
    for image in group.images:
        parts.append(_image_part_to_part(image))
    if not parts:
        parts.append(types.Part(text=""))
    return types.Content(role="user", parts=parts)


def _tool_groups_to_content(groups: list[ToolGroup], model_name: str | None) -> list[types.Content]:
    supports_multimodal_function_response = bool(model_name and "gemini-3" in model_name.lower())

    response_parts: list[types.Part] = []
    extra_image_contents: list[types.Content] = []

    for group in groups:
        merged_text = merge_reminder_text(
            group.tool_result.output or "<system-reminder>Tool ran without output or errors</system-reminder>",
            group.reminder_texts,
        )
        has_text = merged_text.strip() != ""

        images = list(group.tool_result.images or []) + list(group.reminder_images)
        image_parts: list[types.Part] = []
        for image in images:
            try:
                image_parts.append(_image_part_to_part(image))
            except ValueError:
                # Skip invalid data URLs
                continue

        has_images = len(image_parts) > 0
        response_value = merged_text if has_text else "(see attached image)" if has_images else ""
        response_payload = (
            {"error": response_value} if group.tool_result.status == "error" else {"output": response_value}
        )

        function_response = types.FunctionResponse(
            id=group.tool_result.call_id,
            name=group.tool_result.tool_name or "",
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


def _assistant_group_to_content(group: AssistantGroup, model_name: str | None) -> types.Content | None:
    parts: list[types.Part] = []

    degraded_thinking_texts: list[str] = []
    pending_thought_text: str | None = None
    pending_thought_signature: str | None = None

    for item in group.reasoning_items:
        match item:
            case model.ReasoningTextItem():
                if not item.content:
                    continue
                if model_name is not None and item.model is not None and item.model != model_name:
                    degraded_thinking_texts.append(item.content)
                else:
                    pending_thought_text = item.content
            case model.ReasoningEncryptedItem():
                if not (
                    model_name is not None
                    and item.model == model_name
                    and item.encrypted_content
                    and (item.format or "").startswith("google")
                    and pending_thought_text
                ):
                    continue
                pending_thought_signature = item.encrypted_content
                parts.append(
                    types.Part(
                        text=pending_thought_text,
                        thought=True,
                        thought_signature=pending_thought_signature,
                    )
                )
                pending_thought_text = None
                pending_thought_signature = None

    if pending_thought_text:
        parts.append(
            types.Part(
                text=pending_thought_text,
                thought=True,
                thought_signature=pending_thought_signature,
            )
        )

    if degraded_thinking_texts:
        parts.insert(0, types.Part(text="<thinking>\n" + "\n".join(degraded_thinking_texts) + "\n</thinking>"))

    if group.text_content:
        parts.append(types.Part(text=group.text_content))

    for tc in group.tool_calls:
        args: dict[str, Any]
        if tc.arguments:
            try:
                args = json.loads(tc.arguments)
            except json.JSONDecodeError:
                args = {"_raw": tc.arguments}
        else:
            args = {}
        parts.append(types.Part(function_call=types.FunctionCall(id=tc.call_id, name=tc.name, args=args)))

    if not parts:
        return None
    return types.Content(role="model", parts=parts)


def convert_history_to_contents(
    history: list[model.ConversationItem],
    model_name: str | None,
) -> list[types.Content]:
    contents: list[types.Content] = []
    pending_tool_groups: list[ToolGroup] = []

    def flush_tool_groups() -> None:
        nonlocal pending_tool_groups
        if pending_tool_groups:
            contents.extend(_tool_groups_to_content(pending_tool_groups, model_name=model_name))
            pending_tool_groups = []

    for group in parse_message_groups(history):
        match group:
            case UserGroup():
                flush_tool_groups()
                contents.append(_user_group_to_content(group))
            case ToolGroup():
                pending_tool_groups.append(group)
            case AssistantGroup():
                flush_tool_groups()
                content = _assistant_group_to_content(group, model_name=model_name)
                if content is not None:
                    contents.append(content)

    flush_tool_groups()
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
