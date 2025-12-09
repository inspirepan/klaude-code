from typing import Literal

from pydantic import BaseModel

from klaude_code.protocol import llm_param, model

"""
Event is how Agent Executor and UI Display communicate.
"""


class EndEvent(BaseModel):
    pass


class ErrorEvent(BaseModel):
    error_message: str
    can_retry: bool = False


class TaskStartEvent(BaseModel):
    session_id: str
    sub_agent_state: model.SubAgentState | None = None


class TaskFinishEvent(BaseModel):
    session_id: str
    task_result: str
    has_structured_output: bool = False


class TurnStartEvent(BaseModel):
    """For now, this event is used for UI to flush developer message buffer and print an empty line"""

    session_id: str


class TurnEndEvent(BaseModel):
    session_id: str


class TurnToolCallStartEvent(BaseModel):
    """For UI changing status text"""

    session_id: str
    response_id: str | None = None
    tool_call_id: str
    tool_name: str
    arguments: str


class ThinkingEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    content: str


class ThinkingDeltaEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    content: str


class AssistantMessageDeltaEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    content: str


class AssistantMessageEvent(BaseModel):
    response_id: str | None = None
    session_id: str
    content: str


class DeveloperMessageEvent(BaseModel):
    """DeveloperMessages are reminders in user messages or tool results, see: core/reminders.py"""

    session_id: str
    item: model.DeveloperMessageItem


class ToolCallEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    tool_call_id: str
    tool_name: str
    arguments: str


class ToolResultEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    tool_call_id: str
    tool_name: str
    result: str
    ui_extra: model.ToolResultUIExtra | None = None
    status: Literal["success", "error"]
    task_metadata: model.TaskMetadata | None = None  # Sub-agent task metadata


class ResponseMetadataEvent(BaseModel):
    """Internal event for turn-level metadata. Not exposed to UI directly."""

    session_id: str
    metadata: model.ResponseMetadataItem


class TaskMetadataEvent(BaseModel):
    """Task-level aggregated metadata for UI display."""

    session_id: str
    metadata: model.TaskMetadataItem


class UserMessageEvent(BaseModel):
    session_id: str
    content: str
    images: list[model.ImageURLPart] | None = None


class WelcomeEvent(BaseModel):
    work_dir: str
    llm_config: llm_param.LLMConfigParameter


class InterruptEvent(BaseModel):
    session_id: str


class TodoChangeEvent(BaseModel):
    session_id: str
    todos: list[model.TodoItem]


class ContextUsageEvent(BaseModel):
    """Real-time context usage update during task execution."""

    session_id: str
    context_percent: float  # Context usage percentage (0-100)


HistoryItemEvent = (
    ThinkingEvent
    | TaskStartEvent
    | TaskFinishEvent
    | TurnStartEvent  # This event is used for UI to print new empty line
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | UserMessageEvent
    | TaskMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | ErrorEvent
)


class ReplayHistoryEvent(BaseModel):
    session_id: str
    events: list[HistoryItemEvent]
    updated_at: float
    is_load: bool = True


Event = (
    TaskStartEvent
    | TaskFinishEvent
    | ThinkingEvent
    | ThinkingDeltaEvent
    | AssistantMessageDeltaEvent
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | ResponseMetadataEvent
    | TaskMetadataEvent
    | ReplayHistoryEvent
    | ErrorEvent
    | EndEvent
    | WelcomeEvent
    | UserMessageEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | TodoChangeEvent
    | TurnStartEvent
    | TurnEndEvent
    | TurnToolCallStartEvent
    | ContextUsageEvent
)
