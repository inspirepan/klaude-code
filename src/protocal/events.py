from pydantic import BaseModel

from src.protocal.model import Usage


class Event(BaseModel):
    """
    Event is how Agent Executor and UI Display communicate.
    """

    pass


class EndEvent(Event):
    pass


class ThinkingDeltaEvent(Event):
    session_id: str
    response_id: str | None = None
    content: str


class ThinkingEvent(Event):
    session_id: str
    response_id: str | None = None
    content: str


class AssistantMessageDeltaEvent(Event):
    session_id: str
    response_id: str | None = None
    content: str


class AssistantMessageEvent(Event):
    response_id: str | None = None
    session_id: str
    content: str


class ToolCallEvent(Event):
    response_id: str | None = None
    tool_call_id: str
    tool_name: str
    arguments: str


class ToolCallResultEvent(Event):
    tool_call_id: str
    tool_name: str
    result: str
    extra: str


class ResponseMetadataEvent(Event):
    response_id: str | None = None
    session_id: str
    usage: Usage | None = None


class ErrorEvent(Event):
    error_message: str


class TaskStartEvent(Event):
    session_id: str


class TaskFinishEvent(Event):
    session_id: str
