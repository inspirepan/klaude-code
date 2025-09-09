from typing import Literal

from pydantic import BaseModel

from codex_mini.protocol import llm_parameter, model

"""
Event is how Agent Executor and UI Display communicate.
"""


class EndEvent(BaseModel):
    pass


class ErrorEvent(BaseModel):
    error_message: str


class TaskStartEvent(BaseModel):
    session_id: str


class TaskFinishEvent(BaseModel):
    session_id: str


class TurnStartEvent(BaseModel):
    """For now, this event is used for UI flush developer message buffer"""

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


class ThinkingDeltaEvent(BaseModel):
    session_id: str
    response_id: str | None = None
    content: str


class ThinkingEvent(BaseModel):
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
    annotations: list[model.Annotation] | None = None


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
    ui_extra: str | None = None
    status: Literal["success", "error"]


class ResponseMetadataEvent(BaseModel):
    """Showing model name & usage tokens"""

    session_id: str
    metadata: model.ResponseMetadataItem


class UserMessageEvent(BaseModel):
    session_id: str
    content: str


class WelcomeEvent(BaseModel):
    work_dir: str
    llm_config: llm_parameter.LLMConfigParameter


class InterruptEvent(BaseModel):
    session_id: str


class TodoChangeEvent(BaseModel):
    session_id: str
    todos: list[model.TodoItem]


HistoryItemEvent = (
    ThinkingEvent
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | UserMessageEvent
    | ResponseMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
)


class ReplayHistoryEvent(BaseModel):
    events: list[HistoryItemEvent]
    updated_at: float


Event = (
    TaskStartEvent
    | TaskFinishEvent
    | ThinkingDeltaEvent
    | ThinkingEvent
    | AssistantMessageDeltaEvent
    | AssistantMessageEvent
    | ToolCallEvent
    | ToolResultEvent
    | ResponseMetadataEvent
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
)
