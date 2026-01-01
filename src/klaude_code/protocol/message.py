"""
Models for LLM API input and response items.

History is persisted as HistoryEvent (messages + error/task metadata).
Streaming-only items are emitted at runtime but never persisted.
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from klaude_code.protocol.model import (
    AtPatternParseResult,
    CommandOutput,
    StopReason,
    TaskMetadata,
    TaskMetadataItem,
    ToolResultUIExtra,
    ToolSideEffect,
    ToolStatus,
    Usage,
)

# Stream items


class ToolCallStartItem(BaseModel):
    """Transient streaming signal when LLM starts a tool call.

    This is NOT persisted to conversation history. Used only for
    real-time UI feedback (e.g., "Calling Bash ...").
    """

    response_id: str | None = None
    call_id: str
    name: str
    created_at: datetime = Field(default_factory=datetime.now)


class AssistantMessageDelta(BaseModel):
    response_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class AssistantImageDelta(BaseModel):
    """Streaming signal indicating an image has been saved to disk."""

    response_id: str | None = None
    file_path: str
    created_at: datetime = Field(default_factory=datetime.now)


class ThinkingTextDelta(BaseModel):
    response_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class StreamErrorItem(BaseModel):
    error: str
    created_at: datetime = Field(default_factory=datetime.now)


# Part types


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImageURLPart(BaseModel):
    type: Literal["image_url"] = "image_url"
    url: str
    id: str | None = None


class ImageFilePart(BaseModel):
    type: Literal["image_file"] = "image_file"
    file_path: str
    mime_type: str | None = None
    byte_size: int | None = None
    sha256: str | None = None


class ThinkingTextPart(BaseModel):
    type: Literal["thinking_text"] = "thinking_text"
    id: str | None = None
    text: str
    model_id: str | None = None


class ThinkingSignaturePart(BaseModel):
    type: Literal["thinking_signature"] = "thinking_signature"
    id: str | None = None
    signature: str
    model_id: str | None = None
    format: str | None = None


class ToolCallPart(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    call_id: str
    tool_name: str
    arguments_json: str


Part = Annotated[
    TextPart | ImageURLPart | ImageFilePart | ThinkingTextPart | ThinkingSignaturePart | ToolCallPart,
    Field(discriminator="type"),
]


def _empty_parts() -> list[Part]:
    return []


# Message types


class MessageBase(BaseModel):
    id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    response_id: str | None = None


class SystemMessage(MessageBase):
    role: Literal["system"] = "system"
    parts: list[TextPart]


class DeveloperMessage(MessageBase):
    role: Literal["developer"] = "developer"
    parts: list[Part]

    # Special fields for reminders UI
    memory_paths: list[str] | None = None
    memory_mentioned: dict[str, list[str]] | None = None  # memory_path -> list of @ patterns mentioned in it
    external_file_changes: list[str] | None = None
    todo_use: bool | None = None
    at_files: list[AtPatternParseResult] | None = None
    command_output: CommandOutput | None = None
    user_image_count: int | None = None
    skill_name: str | None = None  # Skill name activated via $skill syntax


class UserMessage(MessageBase):
    role: Literal["user"] = "user"
    parts: list[Part]


class AssistantMessage(MessageBase):
    role: Literal["assistant"] = "assistant"
    parts: list[Part]
    usage: Usage | None = None
    stop_reason: StopReason | None = None


class ToolResultMessage(MessageBase):
    role: Literal["tool"] = "tool"
    call_id: str = ""
    tool_name: str = ""
    status: ToolStatus
    output_text: str
    parts: list[Part] = Field(default_factory=_empty_parts)
    ui_extra: ToolResultUIExtra | None = None
    side_effects: list[ToolSideEffect] | None = None
    task_metadata: TaskMetadata | None = None  # Sub-agent task metadata for propagation to main agent

    @field_validator("parts")
    @classmethod
    def _ensure_non_text_parts(cls, parts: list[Part]) -> list[Part]:
        if any(isinstance(part, TextPart) for part in parts):
            raise ValueError("ToolResultMessage.parts must not include text parts")
        return parts


Message = SystemMessage | DeveloperMessage | UserMessage | AssistantMessage | ToolResultMessage

HistoryEvent = Message | StreamErrorItem | TaskMetadataItem

StreamItem = AssistantMessageDelta | AssistantImageDelta | ThinkingTextDelta | ToolCallStartItem

LLMStreamItem = HistoryEvent | StreamItem


# User input


class UserInputPayload(BaseModel):
    """Structured payload for user input containing text and optional images.

    This is the unified data structure for user input across the entire
    UI -> CLI -> Executor -> Agent -> Task chain.
    """

    text: str
    images: list[ImageURLPart] | None = None


# Helper functions


def text_parts_from_str(text: str | None) -> list[Part]:
    if not text:
        return []
    return [TextPart(text=text)]


def parts_from_text_and_images(text: str | None, images: list[ImageURLPart] | None) -> list[Part]:
    parts: list[Part] = []
    if text:
        parts.append(TextPart(text=text))
    if images:
        parts.extend(images)
    return parts


def join_text_parts(parts: Sequence[Part]) -> str:
    return "".join(part.text for part in parts if isinstance(part, TextPart))
