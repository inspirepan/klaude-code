from __future__ import annotations

import json
import re
import time
from collections.abc import Sequence
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, user_interaction
from klaude_code.protocol.models import (
    SessionStatsUIExtra,
    SubAgentState,
    TaskMetadata,
    TaskMetadataItem,
    TodoItem,
    ToolResultUIExtra,
    Usage,
)

__all__ = [
    "AssistantTextDeltaEvent",
    "AssistantTextEndEvent",
    "AssistantTextStartEvent",
    "AwaySummaryEndEvent",
    "AwaySummaryEvent",
    "AwaySummaryStartEvent",
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
    "FallbackModelConfigWarnEvent",
    "ForkCacheHitRateEvent",
    "InterruptEvent",
    "ModelChangedEvent",
    "NoticeEvent",
    "OperationAcceptedEvent",
    "OperationFinishedEvent",
    "OperationRejectedEvent",
    "PromptSuggestionClearedEvent",
    "PromptSuggestionReadyEvent",
    "ReplayEventUnion",
    "ReplayHistoryEvent",
    "ResponseCompleteEvent",
    "ResponseEvent",
    "RewindEvent",
    "SessionHolderAcquiredEvent",
    "SessionHolderDeniedEvent",
    "SessionHolderReleasedEvent",
    "SessionStatsEvent",
    "SessionTitleChangedEvent",
    "SubAgentModelChangedEvent",
    "TaskFileChangeSummaryEvent",
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
    "ToolOutputDeltaEvent",
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
    "WelcomeStartupInfo",
    "WelcomeUpdateInfo",
    "event_durability",
    "event_type_name",
    "parse_event_envelope",
    "parse_event_envelope_json",
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
        "away.summary",
        "prompt.suggestion.ready",
    }
)


def event_type_name(event: Event) -> str:
    return _event_type_name_from_class_name(event.__class__.__name__)


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
    """DeveloperMessages are attachments in user messages or tool results."""

    item: message.DeveloperMessage


class TodoChangeEvent(Event):
    todos: list[TodoItem]


class NoticeEvent(Event):
    """Generic UI notice message. Not persisted to session history."""

    content: str = ""
    ui_extra: ToolResultUIExtra | None = None
    is_error: bool = False
    style: str | None = None


class AwaySummaryEvent(Event):
    """'While you were away' recap generated after prompt idle, or triggered
    manually via /recap. Persisted via AwaySummaryEntry for dedup and replay.
    """

    text: str


class AwaySummaryStartEvent(Event):
    """Fired before a manual away-summary LLM call begins so the TUI can
    surface a 'Recapping…' spinner status. Ephemeral — UI only."""

    pass


class AwaySummaryEndEvent(Event):
    """Fired after a manual away-summary LLM call completes (success or
    empty/error) so the TUI can exit the 'Recapping…' spinner status.
    Ephemeral — UI only."""

    pass


class PromptSuggestionReadyEvent(Event):
    """Predicted-next-user-prompt ready for display. TUI can pre-fill the
    input placeholder so the user can accept with Enter (empty buffer) or Tab.
    Durable: persisted via PromptSuggestionEntry so replay restores it.
    """

    text: str


class PromptSuggestionClearedEvent(Event):
    """Invalidate the currently displayed prompt suggestion (new turn
    starting, user typed, or explicit reset). Ephemeral — UI only."""

    pass


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


class FallbackModelConfigWarnEvent(Event):
    sub_agent_type: str | None = None
    from_model: str
    from_provider: str | None = None
    to_model: str
    to_provider: str | None = None
    reason: str


class SessionStatsEvent(Event):
    stats: SessionStatsUIExtra


class SessionTitleChangedEvent(Event):
    title: str


class SessionHolderAcquiredEvent(Event):
    """Broadcast when a connection acquires the holder lock."""

    pass


class SessionHolderDeniedEvent(Event):
    """Broadcast when a connection fails to acquire the holder lock."""

    pass


class SessionHolderReleasedEvent(Event):
    """Broadcast when the holder is released (disconnect or explicit release)."""

    pass


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
    sub_agent_state: SubAgentState | None = None
    model_id: str | None = None
    parent_session_id: str | None = None


class CompactionStartEvent(Event):
    reason: Literal["threshold", "overflow", "manual", "handoff"]


class CompactionEndEvent(Event):
    reason: Literal["threshold", "overflow", "manual", "handoff"]
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


class TurnStartEvent(Event):
    pass


class TurnEndEvent(Event):
    pass


class UsageEvent(ResponseEvent):
    usage: Usage


class CacheHitRateEvent(Event):
    cache_hit_rate: float
    cached_tokens: int
    prev_turn_input_tokens: int


class ForkCacheHitRateEvent(Event):
    """Emitted after a forked LLM query (compact, handoff, sub-agent fork_context, ...)
    to surface how much of the parent's prompt cache the fork actually reused.

    Not persisted to history — ephemeral, for TUI display only.
    """

    fork_label: str
    """Identifies the fork source: ``compact`` / ``handoff`` / ``sub_agent`` / ..."""
    cache_read_tokens: int
    cache_creation_tokens: int
    input_tokens: int
    cache_hit_rate: float
    """``cache_read / (cache_read + cache_creation + input)``; ``0.0`` when fallback_used."""
    fallback_used: bool = False
    """True when cache sharing was skipped (e.g. compact_model differs from main)."""


class TaskMetadataEvent(Event):
    metadata: TaskMetadataItem
    # True when emitted as a best-effort snapshot (e.g. task cancellation/interrupt).
    # This can affect UI spacing because a partial task may not emit TaskFinishEvent.
    is_partial: bool = False


class TaskFileChangeSummaryEvent(Event):
    summary: message.TaskFileChangeSummaryEntry


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


class WelcomeUpdateInfo(BaseModel):
    message: str
    level: Literal["info", "warn"] = "warn"


class WelcomeStartupInfo(BaseModel):
    update_info: WelcomeUpdateInfo | None = None


class WelcomeEvent(Event):
    work_dir: str
    llm_config: llm_param.LLMConfigParameter
    title: str | None = None
    show_klaude_code_info: bool = True
    loaded_skills: dict[str, list[str]] = Field(default_factory=dict)
    loaded_skill_warnings: dict[str, list[str]] = Field(default_factory=dict)
    loaded_memories: dict[str, list[str]] = Field(default_factory=dict)
    startup_info: WelcomeStartupInfo | None = None


class ErrorEvent(Event):
    error_message: str
    can_retry: bool = False


class InterruptEvent(Event):
    show_notice: bool = True


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
    | TaskFileChangeSummaryEvent
    | TaskMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | ErrorEvent
    | CompactionStartEvent
    | CompactionEndEvent
    | RewindEvent
    | CacheHitRateEvent
    | FallbackModelConfigWarnEvent
    | BashCommandStartEvent
    | BashCommandOutputDeltaEvent
    | BashCommandEndEvent
    | AwaySummaryEvent
    | PromptSuggestionReadyEvent
)


class ReplayHistoryEvent(Event):
    events: list[ReplayEventUnion]
    updated_at: float
    is_load: bool = True


class ToolCallEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    arguments: str


class ToolOutputDeltaEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    content: str


class ToolResultEvent(ResponseEvent):
    tool_call_id: str
    tool_name: str
    result: str
    ui_extra: ToolResultUIExtra | None = None
    status: Literal["success", "error", "aborted"]
    task_metadata: TaskMetadata | None = None
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


def _event_type_name_from_class_name(class_name: str) -> str:
    event_name = class_name[:-5] if class_name.endswith("Event") else class_name
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+", event_name)
    if not words:
        return "event.unknown"
    return ".".join(word.lower() for word in words)


def _iter_event_classes(base: type[Event]) -> list[type[Event]]:
    classes: list[type[Event]] = []
    for subclass in base.__subclasses__():
        classes.append(subclass)
        classes.extend(_iter_event_classes(subclass))
    return classes


_EVENT_TYPE_TO_CLASS = {
    _event_type_name_from_class_name(event_cls.__name__): event_cls for event_cls in _iter_event_classes(Event)
}


def parse_event_envelope(payload: dict[str, Any]) -> EventEnvelope:
    raw_event_type = payload.get("event_type")
    raw_event = payload.get("event")
    if not isinstance(raw_event_type, str) or not isinstance(raw_event, dict):
        raise ValueError("invalid event envelope payload")

    event_cls = _EVENT_TYPE_TO_CLASS.get(raw_event_type)
    if event_cls is None:
        raise ValueError(f"unknown event type: {raw_event_type}")

    parsed_event = event_cls.model_validate(raw_event)
    return EventEnvelope.model_validate({**payload, "event": parsed_event})


def parse_event_envelope_json(payload: bytes | str) -> EventEnvelope:
    try:
        raw = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("invalid event envelope json") from exc
    if not isinstance(raw, dict):
        raise ValueError("invalid event envelope payload")
    return parse_event_envelope(cast(dict[str, Any], raw))
