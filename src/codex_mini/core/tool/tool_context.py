from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

from codex_mini.session.session import Session

# Holds the current Session for tool execution context.
# Set by Agent/Reminder right before invoking a tool.
current_session_var: ContextVar[Session | None] = ContextVar("current_session", default=None)


# Holds a handle to the current Agent's deactivate_plan_mode for tool execution context.
# The callable returns a message string describing the switch.
current_exit_plan_mode_callback: ContextVar[Callable[[], str] | None] = ContextVar(
    "current_deactivate_plan_mode_callback", default=None
)
