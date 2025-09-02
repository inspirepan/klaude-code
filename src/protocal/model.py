from abc import ABC
from typing import List, Literal, Optional

from pydantic import BaseModel


class ResponseItem(ABC, BaseModel):
    """
    Base class for all response items.
    """

    pass


class ContentItem(BaseModel):
    text: Optional[str] = None
    image: Optional[str] = None


class MessageItem(ResponseItem):
    id: Optional[str] = None
    content: List[ContentItem]
    role: Literal["system", "user", "assistant", "tool"]


class ReasoningItem(ResponseItem):
    id: Optional[str] = None
    summary: Optional[str] = None
    content: Optional[List[ContentItem]] = None
    encrypted_content: Optional[str] = None


class ToolCallItem(ResponseItem):
    id: Optional[str] = None
    name: str
    arguments: str
    call_id: str


class SystemMessage(MessageItem):
    role: Literal["system"] = "system"


class UserMessage(MessageItem):
    role: Literal["user"] = "user"


class AssistantMessage(MessageItem):
    role: Literal["assistant"] = "assistant"


class ToolMessage(MessageItem):
    role: Literal["tool", "user"] = "tool"
