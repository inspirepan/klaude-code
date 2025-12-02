from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, computed_field

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
    context_window_size: int | None = None  # Peak total_tokens seen (for context usage display)
    context_limit: int | None = None  # Model's context limit

    throughput_tps: float | None = None
    first_token_latency_ms: float | None = None

    # Cost (calculated from token counts and cost config)
    input_cost: float | None = None  # Cost for non-cached input tokens
    output_cost: float | None = None  # Cost for output tokens (including reasoning)
    cache_read_cost: float | None = None  # Cost for cached tokens
    currency: str = "USD"  # Currency for cost display (USD or CNY)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_tokens(self) -> int:
        """Total tokens computed from input + output tokens."""
        return self.input_tokens + self.output_tokens

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_cost(self) -> float | None:
        """Total cost computed from input + output + cache_read costs."""
        costs = [self.input_cost, self.output_cost, self.cache_read_cost]
        non_none = [c for c in costs if c is not None]
        return sum(non_none) if non_none else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def context_usage_percent(self) -> float | None:
        """Context usage percentage computed from context_window_size / context_limit."""
        if self.context_limit is None or self.context_limit <= 0:
            return None
        if self.context_window_size is None:
            return None
        return (self.context_window_size / self.context_limit) * 100


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
    SESSION_STATUS = "session_status"


class ToolSideEffect(str, Enum):
    TODO_CHANGE = "todo_change"


class MermaidLinkUIExtra(BaseModel):
    link: str
    line_count: int


class TruncationUIExtra(BaseModel):
    saved_file_path: str
    original_length: int
    truncated_length: int


class SessionStatusUIExtra(BaseModel):
    usage: "Usage"
    task_count: int
    by_model: list["TaskMetadata"] = []


class ToolResultUIExtra(BaseModel):
    type: ToolResultUIExtraType
    diff_text: str | None = None
    todo_list: TodoUIExtra | None = None
    session_id: str | None = None
    mermaid_link: MermaidLinkUIExtra | None = None
    truncation: TruncationUIExtra | None = None
    session_status: SessionStatusUIExtra | None = None


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
    user_image_count: int | None = None


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

            # Accumulate primary token fields (total_tokens is computed)
            agg.usage.input_tokens += usage.input_tokens
            agg.usage.cached_tokens += usage.cached_tokens
            agg.usage.reasoning_tokens += usage.reasoning_tokens
            agg.usage.output_tokens += usage.output_tokens

            # Accumulate cost components (total_cost is computed)
            if usage.input_cost is not None:
                agg.usage.input_cost = (agg.usage.input_cost or 0.0) + usage.input_cost
            if usage.output_cost is not None:
                agg.usage.output_cost = (agg.usage.output_cost or 0.0) + usage.output_cost
            if usage.cache_read_cost is not None:
                agg.usage.cache_read_cost = (agg.usage.cache_read_cost or 0.0) + usage.cache_read_cost

        # Sort by total_cost descending
        return sorted(
            aggregated.values(),
            key=lambda m: m.usage.total_cost if m.usage and m.usage.total_cost else 0.0,
            reverse=True,
        )


class TaskMetadataItem(BaseModel):
    """Aggregated metadata for a complete task, stored in conversation history."""

    main: TaskMetadata = Field(default_factory=TaskMetadata)
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


StreamItem = AssistantMessageDelta

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
