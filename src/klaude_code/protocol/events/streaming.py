from __future__ import annotations

from .base import ResponseEvent


class ThinkingStartEvent(ResponseEvent):
    pass


class ThinkingDeltaEvent(ResponseEvent):
    content: str


class ThinkingEndEvent(ResponseEvent):
    pass


class AssistantTextStartEvent(ResponseEvent):
    pass


class AssistantTextDeltaEvent(ResponseEvent):
    content: str


class AssistantTextEndEvent(ResponseEvent):
    pass


class AssistantImageDeltaEvent(ResponseEvent):
    file_path: str


class ToolCallStartEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    model_id: str | None = None


class ResponseCompleteEvent(ResponseEvent):
    """Final snapshot of the model response."""

    content: str
    thinking_text: str | None = None
