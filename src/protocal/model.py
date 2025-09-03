from typing import Literal

from pydantic import BaseModel

RoleType = Literal["system", "developer", "user", "assistant", "tool"]


class ResponseItem(BaseModel):
    """
    Base class for all LLM API response items.
    Each LLMClient should convert this class from/to specific API response items.
    A typical sequence of response items is:
    - [StartItem]
    - [ThinkingTextDelta] × n
    - [ThinkingTextDone]
    - [ThinkingTextDelta] × n # OpenAI's Reasoning Summary has multiple parts
    - [ThinkingTextDone]
    - [ReasoningItem]
    - [AssistantMessageTextDelta] × n
    - [AssistantMessage]
    - [ToolCallItem] × n
    - [ResponseMetadataItem]
    - Done
    """

    pass


class StartItem(ResponseItem):
    response_id: str


class StreamErrorItem(ResponseItem):
    error: str


class StreamRetriableErrorItem(StreamErrorItem):
    pass


class ContentPart(BaseModel):
    text: str | None = None
    image: str | None = None


class MessageItem(ResponseItem):
    content: list[ContentPart]
    role: RoleType
    id: str | None = None


class ReasoningItem(ResponseItem):
    id: str | None = None
    summary: list[str] | None = None
    content: list[ContentPart] | None = None
    encrypted_content: str | None = None
    response_id: str | None = None


class ToolCallItem(ResponseItem):
    id: str | None = None
    name: str
    arguments: str
    call_id: str
    response_id: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class ResponseMetadataItem(ResponseItem):
    usage: Usage | None = None
    response_id: str | None = None


class SystemMessage(MessageItem):
    role: RoleType = "system"


class DeveloperMessage(MessageItem):
    role: RoleType = "developer"


class UserMessage(MessageItem):
    role: RoleType = "user"


class AssistantMessage(MessageItem):
    role: RoleType = "assistant"
    response_id: str | None = None


class ToolMessage(MessageItem):
    role: RoleType = "tool"
    call_id: str = ""
    status: Literal["success", "error"]
    ui_extra: str | None = (
        None  # extra information for tool call result, maybe used for UI display
    )


class ThinkingTextDelta(ResponseItem):
    thinking: str
    response_id: str | None = None


class ThinkingTextDone(ResponseItem):
    thinking: str
    response_id: str | None = None


class AssistantMessageTextDelta(ResponseItem):
    content: str
    response_id: str | None = None
