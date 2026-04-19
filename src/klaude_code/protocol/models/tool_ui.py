from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from klaude_code.protocol.models.task_metadata import TaskMetadata
from klaude_code.protocol.models.todo import TodoItem
from klaude_code.protocol.models.usage import Usage


class TodoUIExtra(BaseModel):
    todos: list[TodoItem]
    new_completed: list[str]


class ToolSideEffect(str, Enum):
    TODO_CHANGE = "todo_change"


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
    raw_unified_diff: str | None = None


class TodoListUIExtra(BaseModel):
    type: Literal["todo_list"] = "todo_list"
    todo_list: TodoUIExtra


class SessionIdUIExtra(BaseModel):
    type: Literal["session_id"] = "session_id"
    session_id: str


class ImageUIExtra(BaseModel):
    type: Literal["image"] = "image"
    file_path: str


class MarkdownDocUIExtra(BaseModel):
    type: Literal["markdown_doc"] = "markdown_doc"
    file_path: str
    content: str


class ReadPreviewLine(BaseModel):
    line_no: int
    content: str


class ReadPreviewUIExtra(BaseModel):
    type: Literal["read_preview"] = "read_preview"
    lines: list[ReadPreviewLine]
    remaining_lines: int


class AskUserQuestionSummaryItem(BaseModel):
    question: str
    summary: str
    answered: bool


class AskUserQuestionSummaryUIExtra(BaseModel):
    type: Literal["ask_user_question_summary"] = "ask_user_question_summary"
    items: list[AskUserQuestionSummaryItem]


def _empty_task_metadata_list() -> list[TaskMetadata]:
    return []


class SessionStatsUIExtra(BaseModel):
    type: Literal["session_stats"] = "session_stats"
    events_file_path: str
    session_id: str
    user_messages_count: int
    assistant_messages_count: int
    tool_calls_count: int
    tool_results_count: int
    total_messages_count: int
    usage: Usage
    task_count: int
    by_model: list[TaskMetadata] = Field(default_factory=_empty_task_metadata_list)


MultiUIExtraItem = (
    DiffUIExtra
    | TodoListUIExtra
    | SessionIdUIExtra
    | ImageUIExtra
    | MarkdownDocUIExtra
    | SessionStatsUIExtra
    | ReadPreviewUIExtra
    | AskUserQuestionSummaryUIExtra
)


class MultiUIExtra(BaseModel):
    """A container UIExtra that can render multiple UI blocks for a single tool result."""

    type: Literal["multi"] = "multi"
    items: list[MultiUIExtraItem]


ToolResultUIExtra = Annotated[
    DiffUIExtra
    | TodoListUIExtra
    | SessionIdUIExtra
    | ImageUIExtra
    | MarkdownDocUIExtra
    | SessionStatsUIExtra
    | AskUserQuestionSummaryUIExtra
    | MultiUIExtra
    | ReadPreviewUIExtra,
    Field(discriminator="type"),
]

__all__ = [
    "AskUserQuestionSummaryItem",
    "AskUserQuestionSummaryUIExtra",
    "DiffFileDiff",
    "DiffLine",
    "DiffSpan",
    "DiffUIExtra",
    "ImageUIExtra",
    "MarkdownDocUIExtra",
    "MultiUIExtra",
    "MultiUIExtraItem",
    "ReadPreviewLine",
    "ReadPreviewUIExtra",
    "SessionIdUIExtra",
    "SessionStatsUIExtra",
    "TodoListUIExtra",
    "TodoUIExtra",
    "ToolResultUIExtra",
    "ToolSideEffect",
]
