from typing import Literal, Union

from pydantic import BaseModel

from codex_mini.protocol.model import Usage

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
    session_id: str
    response_id: str | None = None
    usage: Usage | None = None
    model_name: str
    provider: str | None = None  # OpenRouter's provider name


Event = Union[
    TaskStartEvent,
    TaskFinishEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    AssistantMessageDeltaEvent,
    AssistantMessageEvent,
    ToolCallEvent,
    ToolResultEvent,
    ResponseMetadataEvent,
    ErrorEvent,
    EndEvent,
]
