from typing import Literal

from pydantic import BaseModel


class ResponseItem(BaseModel):
    """
    Base class for all response items.
    """

    pass


class ContentItem(BaseModel):
    text: str | None = None
    image: str | None = None


class MessageItem(ResponseItem):
    id: str | None = None
    content: list[ContentItem]
    role: Literal["system", "user", "assistant", "tool"]


class ReasoningItem(ResponseItem):
    id: str | None = None
    summary: str | None = None
    content: list[ContentItem] | None = None
    encrypted_content: str | None = None


class ReasoningItemDelta(ReasoningItem):
    pass


class ToolCallItem(ResponseItem):
    id: str | None = None
    name: str
    arguments: str
    call_id: str


class SystemMessage(MessageItem):
    role: Literal["system", "user", "assistant", "tool"] = "system"


class UserMessage(MessageItem):
    role: Literal["system", "user", "assistant", "tool"] = "user"


class AssistantMessage(MessageItem):
    role: Literal["system", "user", "assistant", "tool"] = "assistant"


class AssistantMessageDelta(AssistantMessage):
    pass


class ToolMessage(MessageItem):
    role: Literal["system", "user", "assistant", "tool"] = "tool"
