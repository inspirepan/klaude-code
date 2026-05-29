"""Provider-agnostic workarounds for model-specific streaming quirks."""

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.model_id import is_deepseek_model
from klaude_code.protocol.models import StopReason


def needs_deepseek_empty_thinking_fallback(
    parts: list[message.Part],
    *,
    param: llm_param.LLMCallParameter,
    stop_reason: StopReason | None,
) -> bool:
    """DeepSeek may emit a tool call without a preceding thinking block.

    When thinking is enabled and a tool call ends the turn, the Anthropic API
    requires a thinking block before tool use; detect the missing-block case.
    """
    if stop_reason != "tool_use":
        return False
    if not param.thinking or param.thinking.type == "disabled":
        return False
    if not is_deepseek_model(str(param.model_id)):
        return False
    if any(isinstance(part, message.ThinkingTextPart) for part in parts):
        return False
    return any(isinstance(part, message.ToolCallPart) for part in parts)


def insert_empty_thinking_before_first_tool_call(parts: list[message.Part], *, model_id: str) -> None:
    """Insert an empty ThinkingTextPart immediately before the first tool call."""
    for index, part in enumerate(parts):
        if isinstance(part, message.ToolCallPart):
            parts.insert(index, message.ThinkingTextPart(text="", model_id=model_id))
            return
