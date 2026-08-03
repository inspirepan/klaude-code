"""Single source of truth for deriving a session's runtime state.

The actor snapshot is authoritative in the single-server model. This helper
replaces the three former copies in routes/server.py, routes/sessions.py, and
session_live.py.
"""

from __future__ import annotations

from typing import Literal, cast

from klaude_code.control.runtime.actor import SessionActorSnapshot
from klaude_code.protocol.models import SessionRuntimeState

type RuntimeStateLiteral = Literal["idle", "running", "waiting_user_input"]


def derive_session_state_from_snapshot(snapshot: SessionActorSnapshot) -> RuntimeStateLiteral:
    if snapshot.pending_request_count > 0:
        return cast(RuntimeStateLiteral, SessionRuntimeState.WAITING_USER_INPUT.value)
    if snapshot.active_root_task is not None or snapshot.child_task_count > 0:
        return cast(RuntimeStateLiteral, SessionRuntimeState.RUNNING.value)
    if not snapshot.is_idle:
        # Operations are enqueued in the actor's mailbox but a root task has
        # not been bound yet; the session is about to run.
        return cast(RuntimeStateLiteral, SessionRuntimeState.RUNNING.value)
    return cast(RuntimeStateLiteral, SessionRuntimeState.IDLE.value)
