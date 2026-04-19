from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from klaude_code.protocol import user_interaction
from klaude_code.protocol.models import FileChangeSummary, FileStatus, SubAgentState, TaskMetadata, TodoItem
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session

type FileTracker = MutableMapping[str, FileStatus]

GetMetadataFn = Callable[[], TaskMetadata | None]
GetProgressFn = Callable[[], str | None]

RunSubtask = Callable[
    [
        SubAgentState,
        Callable[[str], None] | None,
        Callable[[GetMetadataFn], None] | None,
        Callable[[GetProgressFn], None] | None,
    ],
    Awaitable[SubAgentResult],
]

RequestUserInteraction = Callable[
    [
        str,
        user_interaction.UserInteractionSource,
        user_interaction.UserInteractionRequestPayload,
        str | None,
    ],
    Awaitable[user_interaction.UserInteractionResponse],
]

EmitToolOutputDelta = Callable[[str], Awaitable[None]]


@dataclass
class TodoContext:
    """Todo access interface exposed to tools.

    Tools can only read the current todo list and replace it with
    a new list; they cannot access the full Session object.
    """

    get_todos: Callable[[], list[TodoItem]]
    set_todos: Callable[[list[TodoItem]], None]


@dataclass
class SessionTodoStore:
    """Adapter exposing session todos through an explicit interface."""

    session: Session

    def get(self) -> list[TodoItem]:
        return self.session.todos

    def set(self, todos: list[TodoItem]) -> None:
        self.session.todos = todos


def build_todo_context(session: Session) -> TodoContext:
    """Create a TodoContext backed by the given session."""

    store = SessionTodoStore(session)
    return TodoContext(get_todos=store.get, set_todos=store.set)


class HandoffManagerABC(Protocol):
    def send_handoff(self, goal: str) -> str: ...


class RewindManagerABC(Protocol):
    def send_rewind(self, checkpoint_id: int, note: str, rationale: str) -> str: ...


@dataclass(frozen=True)
class ToolContext:
    """Tool execution context.

    This object is shallow-immutable: fields cannot be reassigned, but fields
    may reference mutable objects (e.g., FileTracker).
    """

    file_tracker: FileTracker
    todo_context: TodoContext
    session_id: str
    work_dir: Path
    file_change_summary: FileChangeSummary | None = None
    run_subtask: RunSubtask | None = None
    record_sub_agent_session_id: Callable[[str], None] | None = None
    register_sub_agent_metadata_getter: Callable[[GetMetadataFn], None] | None = None
    register_sub_agent_progress_getter: Callable[[GetProgressFn], None] | None = None
    rewind_manager: RewindManagerABC | None = None
    handoff_manager: HandoffManagerABC | None = None
    request_user_interaction: RequestUserInteraction | None = None
    emit_tool_output_delta: EmitToolOutputDelta | None = None

    def with_record_sub_agent_session_id(self, callback: Callable[[str], None] | None) -> ToolContext:
        return replace(self, record_sub_agent_session_id=callback)

    def with_register_sub_agent_metadata_getter(self, callback: Callable[[GetMetadataFn], None] | None) -> ToolContext:
        return replace(self, register_sub_agent_metadata_getter=callback)

    def with_register_sub_agent_progress_getter(self, callback: Callable[[GetProgressFn], None] | None) -> ToolContext:
        return replace(self, register_sub_agent_progress_getter=callback)

    def with_rewind_manager(self, manager: RewindManagerABC | None) -> ToolContext:
        return replace(self, rewind_manager=manager)

    def with_handoff_manager(self, manager: HandoffManagerABC | None) -> ToolContext:
        return replace(self, handoff_manager=manager)

    def with_request_user_interaction(self, callback: RequestUserInteraction | None) -> ToolContext:
        return replace(self, request_user_interaction=callback)

    def with_emit_tool_output_delta(self, callback: EmitToolOutputDelta | None) -> ToolContext:
        return replace(self, emit_tool_output_delta=callback)
