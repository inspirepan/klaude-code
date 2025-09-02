from abc import ABC

from pydantic import BaseModel


class Event(ABC, BaseModel):
    pass


class EndEvent(Event):
    pass


class AssistantMessageDeltaEvent(Event):
    id: str
    session_id: str
    content: str


class AssistantMessageEvent(Event):
    id: str
    session_id: str
    content: str


class ToolCallEvent(Event):
    tool_call_id: str
    assistant_message_id: str
    tool_name: str
    args: dict


class ToolCallResultEvent(Event):
    tool_call_id: str
    assistant_message_id: str
    tool_name: str
    result: str
    extra: str


class ErrorEvent(Event):
    error_message: str


class TaskStartEvent(Event):
    session_id: str


class TaskFinishEvent(Event):
    session_id: str
