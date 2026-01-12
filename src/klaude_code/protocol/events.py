from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, model
from klaude_code.protocol.commands import CommandName

__all__ = [
    "AssistantImageDeltaEvent",
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "AssistantTextStartEvent",
    "BashCommandEndEvent",
    "BashCommandOutputDeltaEvent",
    "BashCommandStartEvent",
    "CommandOutputEvent",
    "CompactionEndEvent",
    "CompactionStartEvent",
    "DeveloperMessageEvent",
    "EndEvent",
    "ErrorEvent",
    "Event",
    "InterruptEvent",
    "ReplayEventUnion",
    "ReplayHistoryEvent",
    "ResponseCompleteEvent",
    "ResponseEvent",
    "TaskFinishEvent",
    "TaskMetadataEvent",
    "TaskStartEvent",
    "ThinkingDeltaEvent",
    "ThinkingEndEvent",
    "ThinkingStartEvent",
    "TodoChangeEvent",
    "ToolCallEvent",
    "ToolCallStartEvent",
    "ToolResultEvent",
    "TurnEndEvent",
    "TurnStartEvent",
    "UsageEvent",
    "UserMessageEvent",
    "WelcomeEvent",
]


class Event(BaseModel):
    """Base event."""

    session_id: str
    timestamp: float = Field(default_factory=time.time)


class ResponseEvent(Event):
    """Event associated with a single model response."""

    response_id: str | None = None


class UserMessageEvent(Event):
    content: str
    images: Sequence[message.ImageURLPart | message.ImageFilePart] | None = None


class DeveloperMessageEvent(Event):
    """DeveloperMessages are reminders in user messages or tool results."""

    item: message.DeveloperMessage


class TodoChangeEvent(Event):
    todos: list[model.TodoItem]


class CommandOutputEvent(Event):
    """Event for command output display. Not persisted to session history."""

    command_name: CommandName | str
    content: str = ""
    ui_extra: model.ToolResultUIExtra | None = None
    is_error: bool = False


class BashCommandStartEvent(Event):
    command: str


class BashCommandOutputDeltaEvent(Event):
    content: str


class BashCommandEndEvent(Event):
    exit_code: int | None = None
    cancelled: bool = False


class TaskStartEvent(Event):
    sub_agent_state: model.SubAgentState | None = None
    model_id: str | None = None


class CompactionStartEvent(Event):
    reason: Literal["threshold", "overflow", "manual"]


class CompactionEndEvent(Event):
    reason: Literal["threshold", "overflow", "manual"]
    aborted: bool = False
    will_retry: bool = False
    tokens_before: int | None = None
    kept_from_index: int | None = None
    summary: str | None = None
    kept_items_brief: list[message.KeptItemBrief] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]


class TaskFinishEvent(Event):
    task_result: str
    has_structured_output: bool = False


class TurnStartEvent(Event):
    pass


class TurnEndEvent(Event):
    pass


class UsageEvent(ResponseEvent):
    usage: model.Usage


class TaskMetadataEvent(Event):
    metadata: model.TaskMetadataItem


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


class ResponseCompleteEvent(ResponseEvent):
    """Final snapshot of the model response."""

    content: str
    thinking_text: str | None = None


class WelcomeEvent(Event):
    work_dir: str
    llm_config: llm_param.LLMConfigParameter
    show_klaude_code_info: bool = True
    loaded_skills: dict[str, list[str]] = Field(default_factory=dict)
    loaded_memories: dict[str, list[str]] = Field(default_factory=dict)


class ErrorEvent(Event):
    error_message: str
    can_retry: bool = False


class InterruptEvent(Event):
    pass


class EndEvent(Event):
    """Global display shutdown."""

    session_id: str = "__app__"


type ReplayEventUnion = (
    TaskStartEvent
    | TaskFinishEvent
    | TurnStartEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | AssistantTextStartEvent
    | AssistantTextDeltaEvent
    | AssistantTextEndEvent
    | AssistantImageDeltaEvent
    | ToolCallEvent
    | ToolResultEvent
    | UserMessageEvent
    | TaskMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | ErrorEvent
    | CompactionStartEvent
    | CompactionEndEvent
)


class ReplayHistoryEvent(Event):
    events: list[ReplayEventUnion]
    updated_at: float
    is_load: bool = True


class ToolCallEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    arguments: str


class ToolResultEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    result: str
    ui_extra: model.ToolResultUIExtra | None = None
    status: Literal["success", "error", "aborted"]
    task_metadata: model.TaskMetadata | None = None
    is_last_in_turn: bool = True

    @property
    def is_error(self) -> bool:
        return self.status in ("error", "aborted")
