from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from codex_mini.protocol.tools import SubAgentType
from codex_mini.session.session import Session

# Holds the current Session for tool execution context.
# Set by Agent/Reminder right before invoking a tool.
current_session_var: ContextVar[Session | None] = ContextVar("current_session", default=None)


@dataclass
class SubAgentResult:
    task_result: str
    session_id: str
    error: bool = False


# Holds a handle to run a nested subtask (sub-agent) from within a tool call.
# The callable takes a prompt string and a sub-agent type string
# returns the final task_result string and session_id str.
current_run_subtask_callback: ContextVar[Callable[[str, SubAgentType], Awaitable[SubAgentResult]] | None] = ContextVar(
    "current_run_subtask_callback", default=None
)


@dataclass(frozen=True)
class ToolPolicy:
    unrestricted: bool = False


tool_policy_var: ContextVar[ToolPolicy] = ContextVar("tool_policy", default=ToolPolicy())


def set_unrestricted_mode(unrestricted: bool) -> None:
    tool_policy_var.set(ToolPolicy(unrestricted=unrestricted))


def get_tool_policy() -> ToolPolicy:
    return tool_policy_var.get()
