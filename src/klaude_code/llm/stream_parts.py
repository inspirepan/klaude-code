from __future__ import annotations

from collections.abc import MutableSequence

from klaude_code.protocol import message


def append_text_part(parts: MutableSequence[message.Part], text: str) -> int | None:
    if not text:
        return None

    if parts:
        last = parts[-1]
        if isinstance(last, message.TextPart):
            parts[-1] = message.TextPart(text=last.text + text)
            return len(parts) - 1

    parts.append(message.TextPart(text=text))
    return len(parts) - 1


def append_thinking_text_part(
    parts: MutableSequence[message.Part],
    text: str,
    *,
    model_id: str,
    reasoning_field: str | None = None,
    force_new: bool = False,
) -> int | None:
    if not text:
        return None

    if not force_new and parts:
        last = parts[-1]
        if isinstance(last, message.ThinkingTextPart):
            parts[-1] = message.ThinkingTextPart(
                text=last.text + text,
                model_id=model_id,
                reasoning_field=reasoning_field or last.reasoning_field,
            )
            return len(parts) - 1

    parts.append(message.ThinkingTextPart(text=text, model_id=model_id, reasoning_field=reasoning_field))
    return len(parts) - 1


def degrade_thinking_to_text(parts: list[message.Part]) -> list[message.Part]:
    """Degrade thinking parts into a regular TextPart.

    Some providers require thinking signatures/encrypted content to be echoed back
    for subsequent calls. During interruption we cannot reliably determine whether
    we have a complete signature, so we persist thinking as plain text instead.
    """

    thinking_texts: list[str] = []
    non_thinking_parts: list[message.Part] = []

    for part in parts:
        if isinstance(part, message.ThinkingTextPart):
            text = part.text
            if text and text.strip():
                thinking_texts.append(text)
            continue
        if isinstance(part, message.ThinkingSignaturePart):
            continue
        non_thinking_parts.append(part)

    if not thinking_texts:
        return non_thinking_parts

    joined = "\n".join(thinking_texts).strip()
    thinking_block = f"<thinking>\n{joined}\n</thinking>"
    if non_thinking_parts:
        thinking_block += "\n\n"

    return [message.TextPart(text=thinking_block), *non_thinking_parts]


def build_partial_parts(parts: list[message.Part]) -> list[message.Part]:
    filtered_parts: list[message.Part] = [p for p in parts if not isinstance(p, message.ToolCallPart)]
    return degrade_thinking_to_text(filtered_parts)


def build_partial_message(
    parts: list[message.Part],
    *,
    response_id: str | None,
) -> message.AssistantMessage | None:
    partial_parts = build_partial_parts(parts)
    if not partial_parts:
        return None
    return message.AssistantMessage(
        parts=partial_parts,
        response_id=response_id,
        stop_reason="aborted",
    )
