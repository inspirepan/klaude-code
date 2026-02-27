from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, MutableMapping
from dataclasses import dataclass, replace

from klaude_code.core.rewind import RewindManager
from klaude_code.protocol import model, user_interaction
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session

type FileTracker = MutableMapping[str, model.FileStatus]

GetMetadataFn = Callable[[], model.TaskMetadata | None]
GetProgressFn = Callable[[], str | None]

RunSubtask = Callable[
    [
        model.SubAgentState,
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


def build_todo_context(session: Session) -> TodoContext:
    """Create a TodoContext backed by the given session."""

    store = SessionTodoStore(session)
    return TodoContext(get_todos=store.get, set_todos=store.set)


class SubAgentResumeClaims:
    """Track sub-agent resume claims for a single turn.

    Multiple concurrent sub-agent tool calls can attempt to resume the same
    session id in a single model response. This class provides an atomic
    `claim()` operation to reject duplicates.
    """

    def __init__(self) -> None:
        self._claims: set[str] = set()
        self._lock = asyncio.Lock()

    async def claim(self, session_id: str) -> bool:
        async with self._lock:
            if session_id in self._claims:
                return False
            self._claims.add(session_id)
            return True


@dataclass(frozen=True)
class ToolContext:
    """Tool execution context.

    This object is shallow-immutable: fields cannot be reassigned, but fields
    may reference mutable objects (e.g., FileTracker).
    """

    file_tracker: FileTracker
    todo_context: TodoContext
    session_id: str
    run_subtask: RunSubtask | None = None
    sub_agent_resume_claims: SubAgentResumeClaims | None = None
    record_sub_agent_session_id: Callable[[str], None] | None = None
    register_sub_agent_metadata_getter: Callable[[GetMetadataFn], None] | None = None
    register_sub_agent_progress_getter: Callable[[GetProgressFn], None] | None = None
    rewind_manager: RewindManager | None = None
    request_user_interaction: RequestUserInteraction | None = None

    def with_record_sub_agent_session_id(self, callback: Callable[[str], None] | None) -> ToolContext:
        return replace(self, record_sub_agent_session_id=callback)

    def with_register_sub_agent_metadata_getter(self, callback: Callable[[GetMetadataFn], None] | None) -> ToolContext:
        return replace(self, register_sub_agent_metadata_getter=callback)

    def with_register_sub_agent_progress_getter(self, callback: Callable[[GetProgressFn], None] | None) -> ToolContext:
        return replace(self, register_sub_agent_progress_getter=callback)

    def with_rewind_manager(self, manager: RewindManager | None) -> ToolContext:
        return replace(self, rewind_manager=manager)

    def with_request_user_interaction(self, callback: RequestUserInteraction | None) -> ToolContext:
        return replace(self, request_user_interaction=callback)
