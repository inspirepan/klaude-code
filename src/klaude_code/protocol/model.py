from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from klaude_code import const
from klaude_code.protocol.commands import CommandName
from klaude_code.protocol.tools import SubAgentType

RoleType = Literal["system", "developer", "user", "assistant", "tool"]
TodoStatusType = Literal["pending", "in_progress", "completed"]


class Usage(BaseModel):
    # Token Usage (primary state)
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0

    # Context window tracking
    context_size: int | None = None  # Peak total_tokens seen (for context usage display)
    context_limit: int | None = None  # Model's context limit
    max_tokens: int | None = None  # Max output tokens for this request

    throughput_tps: float | None = None
    first_token_latency_ms: float | None = None

    # Cost (calculated from token counts and cost config)
    input_cost: float | None = None  # Cost for non-cached input tokens
    output_cost: float | None = None  # Cost for output tokens (including reasoning)
    cache_read_cost: float | None = None  # Cost for cached tokens
    currency: str = "USD"  # Currency for cost display (USD or CNY)

    @computed_field
    @property
    def total_tokens(self) -> int:
        """Total tokens computed from input + output tokens."""
        return self.input_tokens + self.output_tokens

    @computed_field
    @property
    def total_cost(self) -> float | None:
        """Total cost computed from input + output + cache_read costs."""
        costs = [self.input_cost, self.output_cost, self.cache_read_cost]
        non_none = [c for c in costs if c is not None]
        return sum(non_none) if non_none else None

    @computed_field
    @property
    def context_usage_percent(self) -> float | None:
        """Context usage percentage computed from context_token / (context_limit - max_tokens)."""
        if self.context_limit is None or self.context_limit <= 0:
            return None
        if self.context_size is None:
            return None
        effective_limit = self.context_limit - (self.max_tokens or const.DEFAULT_MAX_TOKENS)
        if effective_limit <= 0:
            return None
        return (self.context_size / effective_limit) * 100


class TodoItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    content: str
    status: TodoStatusType
    active_form: str = Field(default="", alias="activeForm")


class FileStatus(BaseModel):
    """Tracks file state including modification time and content hash.

    Notes:
    - `mtime` is a cheap heuristic and may miss changes on some filesystems.
    - `content_sha256` provides an explicit content-based change detector.
    """

    mtime: float
    content_sha256: str | None = None
    is_memory: bool = False


class TodoUIExtra(BaseModel):
    todos: list[TodoItem]
    new_completed: list[str]


class ToolSideEffect(str, Enum):
    TODO_CHANGE = "todo_change"


# Discriminated union types for ToolResultUIExtra
class DiffSpan(BaseModel):
    op: Literal["equal", "insert", "delete"]
    text: str


class DiffLine(BaseModel):
    kind: Literal["ctx", "add", "remove", "gap"]
    new_line_no: int | None = None
    spans: list[DiffSpan]


class DiffFileDiff(BaseModel):
    file_path: str
    lines: list[DiffLine]
    stats_add: int = 0
    stats_remove: int = 0


class DiffUIExtra(BaseModel):
    type: Literal["diff"] = "diff"
    files: list[DiffFileDiff]


class TodoListUIExtra(BaseModel):
    type: Literal["todo_list"] = "todo_list"
    todo_list: TodoUIExtra


class SessionIdUIExtra(BaseModel):
    type: Literal["session_id"] = "session_id"
    session_id: str


class MermaidLinkUIExtra(BaseModel):
    type: Literal["mermaid_link"] = "mermaid_link"
    code: str = ""
    link: str
    line_count: int


class TruncationUIExtra(BaseModel):
    type: Literal["truncation"] = "truncation"
    saved_file_path: str
    original_length: int
    truncated_length: int


class MarkdownDocUIExtra(BaseModel):
    type: Literal["markdown_doc"] = "markdown_doc"
    file_path: str
    content: str


class SessionStatusUIExtra(BaseModel):
    type: Literal["session_status"] = "session_status"
    usage: "Usage"
    task_count: int
    by_model: list["TaskMetadata"] = []


MultiUIExtraItem = (
    DiffUIExtra
    | TodoListUIExtra
    | SessionIdUIExtra
    | MermaidLinkUIExtra
    | TruncationUIExtra
    | MarkdownDocUIExtra
    | SessionStatusUIExtra
)


class MultiUIExtra(BaseModel):
    """A container UIExtra that can render multiple UI blocks for a single tool result.

    This is primarily used by tools like apply_patch which can perform multiple
    operations in one invocation.
    """

    type: Literal["multi"] = "multi"
    items: list[MultiUIExtraItem]


ToolResultUIExtra = Annotated[
    DiffUIExtra
    | TodoListUIExtra
    | SessionIdUIExtra
    | MermaidLinkUIExtra
    | TruncationUIExtra
    | MarkdownDocUIExtra
    | SessionStatusUIExtra
    | MultiUIExtra,
    Field(discriminator="type"),
]


class AtPatternParseResult(BaseModel):
    path: str
    tool_name: str
    result: str
    tool_args: str
    operation: Literal["Read", "List"]
    images: list["ImageURLPart"] | None = None
    mentioned_in: str | None = None  # Parent file that referenced this file


class CommandOutput(BaseModel):
    command_name: CommandName
    ui_extra: ToolResultUIExtra | None = None
    is_error: bool = False


class SubAgentState(BaseModel):
    sub_agent_type: SubAgentType
    sub_agent_desc: str
    sub_agent_prompt: str
    output_schema: dict[str, Any] | None = None


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
- session/codec.py (ConversationItem registry derived from ConversationItem union)
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
    memory_mentioned: dict[str, list[str]] | None = None  # memory_path -> list of @ patterns mentioned in it
    external_file_changes: list[str] | None = None
    todo_use: bool | None = None
    at_files: list[AtPatternParseResult] | None = None
    command_output: CommandOutput | None = None
    user_image_count: int | None = None
    skill_name: str | None = None  # Skill name activated via $skill syntax


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
    task_metadata: "TaskMetadata | None" = None  # Sub-agent task metadata for propagation to main agent
    created_at: datetime = Field(default_factory=datetime.now)


class AssistantMessageDelta(BaseModel):
    response_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class ReasoningTextDelta(BaseModel):
    response_id: str | None = None
    content: str
    created_at: datetime = Field(default_factory=datetime.now)


class StreamErrorItem(BaseModel):
    error: str
    created_at: datetime = Field(default_factory=datetime.now)


class ResponseMetadataItem(BaseModel):
    """Metadata for a single LLM response (turn-level)."""

    response_id: str | None = None
    usage: Usage | None = None
    model_name: str = ""
    provider: str | None = None  # OpenRouter's provider name
    task_duration_s: float | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class TaskMetadata(BaseModel):
    """Base metadata for a task execution (used by both main and sub-agents)."""

    usage: Usage | None = None
    model_name: str = ""
    provider: str | None = None
    task_duration_s: float | None = None
    turn_count: int = 0

    @staticmethod
    def merge_usage(dst: Usage, src: Usage) -> None:
        """Merge src usage into dst usage (in-place).

        Accumulates token counts and cost components. Does not handle
        special fields like throughput_tps, first_token_latency_ms,
        context_size, or context_limit - those require custom logic.
        """
        dst.input_tokens += src.input_tokens
        dst.cached_tokens += src.cached_tokens
        dst.reasoning_tokens += src.reasoning_tokens
        dst.output_tokens += src.output_tokens

        if src.input_cost is not None:
            dst.input_cost = (dst.input_cost or 0.0) + src.input_cost
        if src.output_cost is not None:
            dst.output_cost = (dst.output_cost or 0.0) + src.output_cost
        if src.cache_read_cost is not None:
            dst.cache_read_cost = (dst.cache_read_cost or 0.0) + src.cache_read_cost

    @staticmethod
    def aggregate_by_model(metadata_list: list["TaskMetadata"]) -> list["TaskMetadata"]:
        """Aggregate multiple TaskMetadata by (model_name, provider).

        Returns a list sorted by total_cost descending.

        Note: total_tokens and total_cost are now computed fields,
        so we only accumulate the primary state fields here.
        """
        aggregated: dict[tuple[str, str | None], TaskMetadata] = {}

        for meta in metadata_list:
            if not meta.usage:
                continue

            key = (meta.model_name, meta.provider)
            usage = meta.usage

            if key not in aggregated:
                aggregated[key] = TaskMetadata(
                    model_name=meta.model_name,
                    provider=meta.provider,
                    usage=Usage(currency=usage.currency),
                )

            agg = aggregated[key]
            if agg.usage is None:
                continue

            TaskMetadata.merge_usage(agg.usage, usage)

        # Sort by total_cost descending
        return sorted(
            aggregated.values(),
            key=lambda m: m.usage.total_cost if m.usage and m.usage.total_cost else 0.0,
            reverse=True,
        )


class TaskMetadataItem(BaseModel):
    """Aggregated metadata for a complete task, stored in conversation history."""

    main_agent: TaskMetadata = Field(default_factory=TaskMetadata)  # Main agent metadata
    sub_agent_task_metadata: list[TaskMetadata] = Field(default_factory=lambda: list[TaskMetadata]())
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


StreamItem = AssistantMessageDelta | ReasoningTextDelta

ConversationItem = (
    StartItem
    | InterruptItem
    | StreamErrorItem
    | StreamItem
    | MessageItem
    | ResponseMetadataItem
    | TaskMetadataItem
    | ToolCallStartItem
)


def todo_list_str(todos: list[TodoItem]) -> str:
    return "[" + "\n".join(f"[{todo.status}] {todo.content}" for todo in todos) + "]\n"
