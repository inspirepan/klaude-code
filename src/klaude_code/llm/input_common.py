"""Common utilities for converting message history to LLM input formats."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from klaude_code.protocol.llm_param import LLMCallParameter, LLMConfigParameter

from klaude_code.protocol import model


def _empty_image_parts() -> list[model.ImageURLPart]:
    return []


@dataclass
class DeveloperAttachment:
    text: str = ""
    images: list[model.ImageURLPart] = field(default_factory=_empty_image_parts)


def _extract_developer_content(message: model.DeveloperMessage) -> tuple[str, list[model.ImageURLPart]]:
    text_parts: list[str] = []
    images: list[model.ImageURLPart] = []
    for part in message.parts:
        if isinstance(part, model.TextPart):
            text_parts.append(part.text + "\n")
        elif isinstance(part, model.ImageURLPart):
            images.append(part)
    return "".join(text_parts), images


def attach_developer_messages(
    messages: Iterable[model.Message],
) -> list[tuple[model.Message, DeveloperAttachment]]:
    """Attach developer messages to the most recent user/tool message.

    Developer messages are removed from the output list and their text/images are
    attached to the previous user/tool message as out-of-band content for provider input.
    """
    message_list = list(messages)
    attachments = [DeveloperAttachment() for _ in message_list]
    last_user_tool_idx: int | None = None

    for idx, msg in enumerate(message_list):
        if isinstance(msg, (model.UserMessage, model.ToolResultMessage)):
            last_user_tool_idx = idx
            continue
        if isinstance(msg, model.DeveloperMessage):
            if last_user_tool_idx is None:
                continue
            dev_text, dev_images = _extract_developer_content(msg)
            attachment = attachments[last_user_tool_idx]
            attachment.text += dev_text
            attachment.images.extend(dev_images)

    result: list[tuple[model.Message, DeveloperAttachment]] = []
    for idx, msg in enumerate(message_list):
        if isinstance(msg, model.DeveloperMessage):
            continue
        result.append((msg, attachments[idx]))

    return result


def merge_reminder_text(tool_output: str | None, reminder_text: str) -> str:
    """Merge tool output with reminder text."""
    base = tool_output or ""
    if reminder_text:
        base += "\n" + reminder_text
    return base


def apply_config_defaults(param: "LLMCallParameter", config: "LLMConfigParameter") -> "LLMCallParameter":
    """Apply config defaults to LLM call parameters."""
    if param.model is None:
        param.model = config.model
    if param.temperature is None:
        param.temperature = config.temperature
    if param.max_tokens is None:
        param.max_tokens = config.max_tokens
    if param.context_limit is None:
        param.context_limit = config.context_limit
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    return param
