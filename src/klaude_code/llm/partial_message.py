from __future__ import annotations

from klaude_code.protocol import message


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
