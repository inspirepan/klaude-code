from __future__ import annotations

from contextvars import ContextVar

from codex_mini.session.session import Session

# Holds the current Session for tool execution context.
# Set by Agent right before invoking a tool.
current_session_var: ContextVar[Session | None] = ContextVar("current_session", default=None)
