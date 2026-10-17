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
    reasoning_format: str | None = None,
    reasoning_id: str | None = None,
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
                format=reasoning_format or last.format,
                id=reasoning_id or last.id,
                duration_s=last.duration_s,
            )
            return len(parts) - 1

    parts.append(
        message.ThinkingTextPart(
            text=text,
            model_id=model_id,
            reasoning_field=reasoning_field,
            format=reasoning_format,
            id=reasoning_id,
        )
    )
    return len(parts) - 1


def build_partial_parts(parts: list[message.Part]) -> list[message.Part]:
    """Build parts for error/interrupt recovery, keeping only plain text content."""
    return [
        p
        for p in parts
        if not isinstance(p, (message.ToolCallPart, message.ThinkingTextPart, message.ThinkingSignaturePart))
    ]


def build_partial_message(
    parts: list[message.Part],
    *,
    response_id: str | None,
    phase: message.AssistantPhase | None = None,
) -> message.AssistantMessage | None:
    partial_parts = build_partial_parts(parts)
    if not partial_parts:
        return None
    return message.AssistantMessage(
        parts=partial_parts,
        response_id=response_id,
        phase=phase,
        stop_reason="aborted",
    )
