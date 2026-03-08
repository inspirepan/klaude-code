from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, model, user_interaction

__all__ = [
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "AssistantTextStartEvent",
    "BashCommandEndEvent",
    "BashCommandOutputDeltaEvent",
    "BashCommandStartEvent",
    "CacheHitRateEvent",
    "CompactModelChangedEvent",
    "CompactionEndEvent",
    "CompactionStartEvent",
    "DeveloperMessageEvent",
    "EndEvent",
    "ErrorEvent",
    "Event",
    "EventEnvelope",
    "InterruptEvent",
    "ModelChangedEvent",
    "NoticeEvent",
    "OperationAcceptedEvent",
    "OperationFinishedEvent",
    "OperationRejectedEvent",
    "ReplayEventUnion",
    "ReplayHistoryEvent",
    "ResponseCompleteEvent",
    "ResponseEvent",
    "RewindEvent",
    "SessionStatsEvent",
    "SessionTitleChangedEvent",
    "SubAgentModelChangedEvent",
    "TaskFinishEvent",
    "TaskMetadataEvent",
    "TaskStartEvent",
    "ThinkingChangedEvent",
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
    "UserInteractionCancelledEvent",
    "UserInteractionRequestEvent",
    "UserInteractionResolvedEvent",
    "UserInteractionResponseReceivedEvent",
    "UserMessageEvent",
    "WelcomeEvent",
]


class Event(BaseModel):
    """Base event."""

    session_id: str
    timestamp: float = Field(default_factory=time.time)


class EventEnvelope(BaseModel):
    event_id: str
    event_seq: int
    session_id: str
    operation_id: str | None = None
    task_id: str | None = None
    causation_id: str | None = None
    event_type: str
    durability: Literal["durable", "ephemeral"]
    timestamp: float
    event: Event


DURABLE_EVENT_TYPES = frozenset(
    {
        "user.message",
        "assistant.text.end",
        "tool.result",
        "rewind",
        "compaction.end",
        "task.finish",
    }
)


def event_type_name(event: Event) -> str:
    event_name = event.__class__.__name__
    if event_name.endswith("Event"):
        event_name = event_name[:-5]

    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+", event_name)
    if not words:
        return "event.unknown"

    return ".".join(word.lower() for word in words)


def event_durability(event_type: str) -> Literal["durable", "ephemeral"]:
    if event_type in DURABLE_EVENT_TYPES:
        return "durable"
    return "ephemeral"


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


class NoticeEvent(Event):
    """Generic UI notice message. Not persisted to session history."""

    content: str = ""
    ui_extra: model.ToolResultUIExtra | None = None
    is_error: bool = False


class ModelChangedEvent(Event):
    model_id: str
    saved_as_default: bool = False


class ThinkingChangedEvent(Event):
    previous: str
    current: str


class SubAgentModelChangedEvent(Event):
    sub_agent_type: str
    model_display: str
    saved_as_default: bool = False


class CompactModelChangedEvent(Event):
    model_display: str
    saved_as_default: bool = False


class SessionStatsEvent(Event):
    stats: model.SessionStatsUIExtra


class SessionTitleChangedEvent(Event):
    title: str


class OperationAcceptedEvent(Event):
    operation_id: str
    operation_type: str


class OperationRejectedEvent(Event):
    operation_id: str
    operation_type: str
    reason: Literal["session_busy"]
    active_task_id: str | None = None


class OperationFinishedEvent(Event):
    operation_id: str
    operation_type: str
    status: Literal["completed", "rejected", "failed"]
    error_message: str | None = None


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


class RewindEvent(Event):
    checkpoint_id: int
    note: str
    rationale: str
    original_user_message: str
    messages_discarded: int | None = None


class TaskFinishEvent(Event):
    task_result: str
    has_structured_output: bool = False


class TurnStartEvent(Event):
    pass


class TurnEndEvent(Event):
    pass


class UsageEvent(ResponseEvent):
    usage: model.Usage


class CacheHitRateEvent(Event):
    cache_hit_rate: float
    cached_tokens: int
    prev_turn_input_tokens: int


class TaskMetadataEvent(Event):
    metadata: model.TaskMetadataItem
    # True when emitted as a best-effort snapshot (e.g. task cancellation/interrupt).
    # This can affect UI spacing because a partial task may not emit TaskFinishEvent.
    is_partial: bool = False


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
    title: str | None = None
    show_klaude_code_info: bool = True
    loaded_skills: dict[str, list[str]] = Field(default_factory=dict)
    loaded_skill_warnings: dict[str, list[str]] = Field(default_factory=dict)
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
    | UsageEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | AssistantTextStartEvent
    | AssistantTextDeltaEvent
    | AssistantTextEndEvent
    | ToolCallEvent
    | ToolResultEvent
    | UserMessageEvent
    | TaskMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | ErrorEvent
    | CompactionStartEvent
    | CompactionEndEvent
    | RewindEvent
    | CacheHitRateEvent
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


class UserInteractionRequestEvent(Event):
    request_id: str
    source: user_interaction.UserInteractionSource
    tool_call_id: str | None = None
    payload: user_interaction.UserInteractionRequestPayload


class UserInteractionResponseReceivedEvent(Event):
    request_id: str
    status: Literal["submitted", "cancelled"]


class UserInteractionResolvedEvent(Event):
    request_id: str
    status: Literal["submitted", "cancelled"]


class UserInteractionCancelledEvent(Event):
    request_id: str
    reason: Literal["user_cancelled", "interrupt", "shutdown", "session_close"]
