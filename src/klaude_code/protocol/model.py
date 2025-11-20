from collections.abc import Iterator
from typing import Iterable, Literal

from pydantic import BaseModel

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


class AtPatternParseResult(BaseModel):
    path: str
    tool_name: str
    result: str
    tool_args: str
    operation: Literal["Read", "List"]
    images: list["ImageURLPart"] | None = None


class CommandOutput(BaseModel):
    command_name: CommandName
    ui_extra: str | None = None
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


class InterruptItem(BaseModel):
    pass


class SystemMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "system"
    content: str | None = None


class DeveloperMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "developer"
    content: str | None = None  # For LLM input
    images: list["ImageURLPart"] | None = None

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


class UserMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "user"
    content: str | None = None
    images: list[ImageURLPart] | None = None


class AssistantMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "assistant"
    content: str | None = None
    response_id: str | None = None


class ReasoningTextItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    content: str


class ReasoningEncryptedItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    encrypted_content: str
    format: str | None = None
    model: str | None


class ToolCallItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    call_id: str
    name: str
    arguments: str


class ToolResultItem(BaseModel):
    call_id: str = ""  # This field will auto set by tool registry's run_tool
    output: str | None = None
    status: Literal["success", "error"]
    tool_name: str | None = None  # This field will auto set by tool registry's run_tool
    ui_extra: str | None = None  # Extra data for UI display, e.g. diff render
    images: list[ImageURLPart] | None = None


class AssistantMessageDelta(BaseModel):
    response_id: str | None = None
    content: str


class StreamErrorItem(BaseModel):
    error: str


class ResponseMetadataItem(BaseModel):
    response_id: str | None = None
    usage: Usage | None = None
    model_name: str = ""
    provider: str | None = None  # OpenRouter's provider name
    task_duration_s: float | None = None
    status: str | None = None
    error_reason: str | None = None


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

ConversationItem = StartItem | InterruptItem | StreamErrorItem | StreamItem | MessageItem | ResponseMetadataItem


def group_response_items_gen(
    items: Iterable[ConversationItem],
) -> Iterator[tuple[Literal["assistant", "user", "tool", "other"], list[ConversationItem]]]:
    """
    Group response items into sublists with predictable attachment rules:
    - Consecutive assistant-side items (ReasoningTextItem | ReasoningEncryptedItem | AssistantMessageItem | ToolCallItem) group together.
    - Consecutive UserMessage group together.
    - Each ToolMessage (ToolResultItem) is a single group, but allow following DeveloperMessage to attach to it.
    - DeveloperMessage only attaches to the previous UserMessage/ToolMessage group.
    """

    # Current buffered group and its kind; None means no active group
    buffer: list[ConversationItem] = []
    buffer_kind: Literal["assistant", "user", "tool", "other"] | None = None

    def kind_of(it: ConversationItem) -> Literal["assistant", "user", "tool", "developer", "other"]:
        if isinstance(it, (ReasoningTextItem, ReasoningEncryptedItem, AssistantMessageItem, ToolCallItem)):
            return "assistant"
        if isinstance(it, UserMessageItem):
            return "user"
        if isinstance(it, ToolResultItem):
            return "tool"
        if isinstance(it, DeveloperMessageItem):
            return "developer"
        return "other"  # Metadata etc.

    def flush() -> Iterator[tuple[Literal["assistant", "user", "tool", "other"], list[ConversationItem]]]:
        nonlocal buffer, buffer_kind
        if buffer and buffer_kind is not None:
            yield (buffer_kind, buffer)
        # reset
        buffer = []
        buffer_kind = None

    for item in items:
        k = kind_of(item)
        if k == "other":
            continue

        if k == "developer":
            # Attach only to previous user/tool group
            if buffer and buffer_kind in ("user", "tool"):
                buffer.append(item)
            # else: drop developer if there's no suitable previous group
            continue

        if not buffer:
            buffer = [item]
            buffer_kind = "tool" if k == "tool" else k
            continue

        # Same kind merge rules: assistant/user merge; tool stays single
        if k == buffer_kind and k != "tool":
            buffer.append(item)
            continue

        # Kind switched or consecutive tool: flush current, start new
        yield from flush()
        buffer = [item]
        buffer_kind = "tool" if k == "tool" else k

    if buffer and buffer_kind is not None:
        yield (buffer_kind, buffer)


def todo_list_str(todos: list[TodoItem]) -> str:
    return "[" + "\n".join(f"[{todo.status}] {todo.content}" for todo in todos) + "]\n"
