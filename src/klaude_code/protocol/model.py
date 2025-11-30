from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.tools import SubAgentType

RoleType = Literal["system", "developer", "user", "assistant", "tool"]
TodoStatusType = Literal["pending", "in_progress", "completed"]


class Usage(BaseModel):
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    context_usage_percent: float | None = None
    throughput_tps: float | None = None
    first_token_latency_ms: float | None = None


class TodoItem(BaseModel):
    content: str
    status: TodoStatusType
    activeForm: str = ""


class TodoUIExtra(BaseModel):
    todos: list[TodoItem]
    new_completed: list[str]


class ToolResultUIExtraType(str, Enum):
    DIFF_TEXT = "diff_text"
    TODO_LIST = "todo_list"
    SESSION_ID = "session_id"
    MERMAID_LINK = "mermaid_link"
    TRUNCATION = "truncation"


class ToolSideEffect(str, Enum):
    TODO_CHANGE = "todo_change"


class MermaidLinkUIExtra(BaseModel):
    link: str
    line_count: int


class TruncationUIExtra(BaseModel):
    saved_file_path: str
    original_length: int
    truncated_length: int


class ToolResultUIExtra(BaseModel):
    type: ToolResultUIExtraType
    diff_text: str | None = None
    todo_list: TodoUIExtra | None = None
    session_id: str | None = None
    mermaid_link: MermaidLinkUIExtra | None = None
    truncation: TruncationUIExtra | None = None


class AtPatternParseResult(BaseModel):
    path: str
    tool_name: str
    result: str
    tool_args: str
    operation: Literal["Read", "List"]
    images: list["ImageURLPart"] | None = None


class CommandOutput(BaseModel):
    command_name: CommandName
    ui_extra: ToolResultUIExtra | None = None
    is_error: bool = False


class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str


"""
Models for LLM API input and response items.

A typical sequence of response items is:
- [StartItem]
- [ReasoningTextItem | ReasoningEncryptedItem]
- [AssistantMessageDelta] × n
- [AssistantMessageItem]
- [ToolCallItem] × n
- [ResponseMetadataItem]
- Done

A conversation history input contains:
- [UserMessageItem]
- [ReasoningTextItem | ReasoningEncryptedItem]
- [AssistantMessageItem]
- [ToolCallItem]
- [ToolResultItem]
- [InterruptItem]
- [DeveloperMessageItem]

When adding a new item, please also modify the following:
- session.py#_TypeMap
"""


class StartItem(BaseModel):
    response_id: str
    created_at: datetime = Field(default_factory=datetime.now)


class InterruptItem(BaseModel):
    created_at: datetime = Field(default_factory=datetime.now)


class SystemMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "system"
    content: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class DeveloperMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "developer"
    content: str | None = None  # For LLM input
    images: list["ImageURLPart"] | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    # Special fields for reminders UI
    memory_paths: list[str] | None = None
    external_file_changes: list[str] | None = None
    todo_use: bool | None = None
    at_files: list[AtPatternParseResult] | None = None
    command_output: CommandOutput | None = None
    clipboard_images: list[str] | None = None


class ImageURLPart(BaseModel):
    class ImageURL(BaseModel):
        url: str
        id: str | None = None

    image_url: ImageURL


class UserInputPayload(BaseModel):
    """Structured payload for user input containing text and optional images.

    This is the unified data structure for user input across the entire
    UI -> CLI -> Executor -> Agent -> Task chain.
    """

    text: str
    images: list["ImageURLPart"] | None = None


class UserMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "user"
    content: str | None = None
    images: list[ImageURLPart] | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class AssistantMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "assistant"
    content: str | None = None
    response_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class ReasoningTextItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    content: str
    model: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class ReasoningEncryptedItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    encrypted_content: str  # OpenAI encrypted content or Anthropic thinking signature
    format: str | None = None
    model: str | None
    created_at: datetime = Field(default_factory=datetime.now)


class ToolCallStartItem(BaseModel):
    """Transient streaming signal when LLM starts a tool call.

    This is NOT persisted to conversation history. Used only for
    real-time UI feedback (e.g., "Calling Bash ...").
    """

    response_id: str | None = None
    call_id: str
    name: str
    created_at: datetime = Field(default_factory=datetime.now)


class ToolCallItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    call_id: str
    name: str
    arguments: str
    created_at: datetime = Field(default_factory=datetime.now)


class ToolResultItem(BaseModel):
    call_id: str = ""  # This field will auto set by tool registry's run_tool
    output: str | None = None
    status: Literal["success", "error"]
    tool_name: str | None = None  # This field will auto set by tool registry's run_tool
    ui_extra: ToolResultUIExtra | None = None  # Extra data for UI display, e.g. diff render
    images: list[ImageURLPart] | None = None
    side_effects: list[ToolSideEffect] | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class AssistantMessageDelta(BaseModel):
    response_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class StreamErrorItem(BaseModel):
    error: str
    created_at: datetime = Field(default_factory=datetime.now)


class ResponseMetadataItem(BaseModel):
    response_id: str | None = None
    usage: Usage | None = None
    model_name: str = ""
    provider: str | None = None  # OpenRouter's provider name
    task_duration_s: float | None = None
    status: str | None = None
    error_reason: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)


MessageItem = (
    UserMessageItem
    | AssistantMessageItem
    | SystemMessageItem
    | DeveloperMessageItem
    | ReasoningTextItem
    | ReasoningEncryptedItem
    | ToolCallItem
    | ToolResultItem
)


StreamItem = AssistantMessageDelta

ConversationItem = (
    StartItem | InterruptItem | StreamErrorItem | StreamItem | MessageItem | ResponseMetadataItem | ToolCallStartItem
)


def todo_list_str(todos: list[TodoItem]) -> str:
    return "[" + "\n".join(f"[{todo.status}] {todo.content}" for todo in todos) + "]\n"
