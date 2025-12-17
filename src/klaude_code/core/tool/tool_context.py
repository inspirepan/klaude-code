from __future__ import annotations

from collections.abc import Awaitable, Callable, Generator, MutableMapping
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from klaude_code.protocol import model
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session

type FileTracker = MutableMapping[str, model.FileStatus]


@dataclass
class TodoContext:
    """Todo access interface exposed to tools.

    Tools can only read the current todo list and replace it with
    a new list; they cannot access the full Session object.
    """

    get_todos: Callable[[], list[model.TodoItem]]
    set_todos: Callable[[list[model.TodoItem]], None]


@dataclass
class SessionTodoStore:
    """Adapter exposing session todos through an explicit interface."""

    session: Session

    def get(self) -> list[model.TodoItem]:
        return self.session.todos

    def set(self, todos: list[model.TodoItem]) -> None:
        self.session.todos = todos


@dataclass
class ToolContextToken:
    """Tokens used to restore tool execution context.

    This captures the contextvar tokens for the current file tracker
    and todo context so callers can safely reset them after a tool
    finishes running.
    """

    file_tracker_token: Token[FileTracker | None] | None
    todo_token: Token[TodoContext | None] | None


# Holds the current file tracker mapping for tool execution context.
# Set by Agent/Reminder right before invoking a tool.
current_file_tracker_var: ContextVar[FileTracker | None] = ContextVar("current_file_tracker", default=None)


# Holds the todo access context for tools.
current_todo_context_var: ContextVar[TodoContext | None] = ContextVar("current_todo_context", default=None)


def set_tool_context_from_session(session: Session) -> ToolContextToken:
    """Bind the given session's file tracker and todos into tool context.

    This should be called by the Agent or reminder helpers immediately
    before invoking tools so that file and todo tools can operate on
    the correct per-session state without seeing the full Session.
    """

    file_tracker_token = current_file_tracker_var.set(session.file_tracker)
    todo_ctx = build_todo_context(session)
    todo_token = current_todo_context_var.set(todo_ctx)
    return ToolContextToken(file_tracker_token=file_tracker_token, todo_token=todo_token)


def reset_tool_context(token: ToolContextToken) -> None:
    """Restore tool execution context from a previously captured token."""

    if token.file_tracker_token is not None:
        current_file_tracker_var.reset(token.file_tracker_token)
    if token.todo_token is not None:
        current_todo_context_var.reset(token.todo_token)


@contextmanager
def tool_context(file_tracker: FileTracker, todo_ctx: TodoContext) -> Generator[ToolContextToken]:
    """Context manager for setting and resetting tool execution context."""

    file_tracker_token = current_file_tracker_var.set(file_tracker)
    todo_token = current_todo_context_var.set(todo_ctx)
    token = ToolContextToken(file_tracker_token=file_tracker_token, todo_token=todo_token)
    try:
        yield token
    finally:
        reset_tool_context(token)


def build_todo_context(session: Session) -> TodoContext:
    """Create a TodoContext backed by the given session."""

    store = SessionTodoStore(session)
    return TodoContext(get_todos=store.get, set_todos=store.set)


def get_current_file_tracker() -> FileTracker | None:
    """Return the current file tracker mapping for this tool context."""

    return current_file_tracker_var.get()


def get_current_todo_context() -> TodoContext | None:
    """Return the current todo access context for this tool context."""

    return current_todo_context_var.get()


# Holds a handle to run a nested subtask (sub-agent) from within a tool call.
# The callable takes a model.SubAgentState and returns a SubAgentResult.
current_run_subtask_callback: ContextVar[Callable[[model.SubAgentState], Awaitable[SubAgentResult]] | None] = (
    ContextVar("current_run_subtask_callback", default=None)
)
