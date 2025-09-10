from collections.abc import Iterator
from typing import Iterable, Literal

from pydantic import BaseModel, TypeAdapter

from codex_mini.protocol.commands import CommandName

RoleType = Literal["system", "developer", "user", "assistant", "tool"]
TodoStatusType = Literal["pending", "in_progress", "completed"]


class Usage(BaseModel):
    input_tokens: int = 0
    cached_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TodoItem(BaseModel):
    content: str
    status: TodoStatusType
    activeForm: str = ""


class TodoUIExtra(BaseModel):
    todos: list[TodoItem]
    new_completed: list[str]


class URLCitation(BaseModel):
    url: str
    title: str
    content: str
    start_index: int
    end_index: int


class Annotation(BaseModel):
    type: Literal["url_citation"]
    url_citation: URLCitation | None = None


Annotations = TypeAdapter(list[Annotation])


class AtPatternParseResult(BaseModel):
    path: str
    tool_name: str
    result: str
    tool_args: str
    operation: Literal["Read", "List"]


class CommandOutput(BaseModel):
    command_name: CommandName
    ui_extra: str | None = None
    is_error: bool = False


"""
Models for LLM API input and response items.

A typical sequence of response items is:
- [StartItem]
- [ThinkingTextDelta] × n
- [ThinkingTextItem]
- [ThinkingTextDelta] × n # OpenAI's Reasoning Summary has multiple parts
- [ThinkingTextItem]
- [ReasoningItem]
- [AssistantMessageDelta] × n
- [AssistantMessageItem]
- [ToolCallItem] × n
- [ResponseMetadataItem]
- Done

A conversation history input contains:
- [UserMessageItem]
- [ReasoningItem]
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

    # Special fields for reminders UI
    memory_paths: list[str] | None = None
    external_file_changes: list[str] | None = None
    todo_use: bool | None = None
    at_files: list[AtPatternParseResult] | None = None
    command_output: CommandOutput | None = None


class UserMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "user"
    content: str | None = None


class AssistantMessageItem(BaseModel):
    id: str | None = None
    role: RoleType = "assistant"
    content: str | None = None
    response_id: str | None = None
    annotations: list[Annotation] | None = None


class ThinkingTextDelta(BaseModel):
    response_id: str | None = None
    thinking: str


class ThinkingTextItem(BaseModel):
    response_id: str | None = None
    thinking: str


class ReasoningItem(BaseModel):
    id: str | None = None
    response_id: str | None = None
    summary: list[str] | None = None
    content: str | None = None
    encrypted_content: str | None = None
    format: str | None = None  # For OpenRouter's reasoning detail
    model: str | None  # Prevent mixing encrypted_content from different models


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


MessageItem = (
    UserMessageItem
    | AssistantMessageItem
    | SystemMessageItem
    | DeveloperMessageItem
    | ThinkingTextItem
    | ReasoningItem
    | ToolCallItem
    | ToolResultItem
)


StreamItem = ThinkingTextDelta | AssistantMessageDelta

ConversationItem = StartItem | InterruptItem | StreamErrorItem | StreamItem | MessageItem | ResponseMetadataItem


def group_response_items_gen(
    items: Iterable[ConversationItem],
) -> Iterator[tuple[Literal["assistant", "user", "tool", "other"], list[ConversationItem]]]:
    """
    Group response items into sublists:
    - Consecutive (ReasoningItem | AssistantMessage | ToolCallItem) are grouped together
    - Consecutive UserMessage are grouped together
    - Each ToolMessage is always a single group
    - Each DeveloperMessage should attach to the previous UserMessage/ToolMessage group
    """
    buffer: list[ConversationItem] = []
    buffer_kind: Literal["assistant", "user", "tool", "other"] = "other"

    def kind_of(
        it: ConversationItem,
    ) -> Literal["assistant", "user", "tool", "developer", "other"]:
        if isinstance(it, (ReasoningItem, AssistantMessageItem, ToolCallItem)):
            return "assistant"
        if isinstance(it, UserMessageItem):
            return "user"
        if isinstance(it, ToolResultItem):
            return "tool"
        if isinstance(it, DeveloperMessageItem):
            return "developer"
        return "other"  # Metadata etc.

    for item in items:
        k = kind_of(item)

        if k == "other":
            continue

        if k == "tool":
            # ToolMessage: flush current buffer and yield as single group
            if buffer:
                yield (buffer_kind, buffer)
                buffer, buffer_kind = [], "other"
            yield ("tool", [item])
            continue

        if k == "developer":
            # DeveloperMessage: attach to UserMessage or ToolMessage as <system-reminder>
            if buffer:
                buffer.append(item)
            continue

        if not buffer:
            buffer = [item]
            buffer_kind = k
        else:
            if k == buffer_kind:
                buffer.append(item)
            else:
                # Type switched, flush current buffer
                yield (buffer_kind, buffer)
                buffer = [item]
                buffer_kind = k

    if buffer:
        yield (buffer_kind, buffer)


def todo_list_str(todos: list[TodoItem]) -> str:
    return "[" + "\n".join(f"[{todo.status}] {todo.content}" for todo in todos) + "]\n"
