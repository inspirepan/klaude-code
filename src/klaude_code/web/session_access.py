from __future__ import annotations

import time
from pathlib import Path
from typing import TYPE_CHECKING

from klaude_code.protocol.models import SessionOwner, SessionRuntimeState
from klaude_code.session.session import Session

if TYPE_CHECKING:
    from klaude_code.web.state import WebAppState

OWNER_HEARTBEAT_TIMEOUT_SECONDS = 15.0

_ACTIVE_SESSION_STATES = (
    SessionRuntimeState.RUNNING,
    SessionRuntimeState.WAITING_USER_INPUT,
    "running",
    "waiting_user_input",
)


def is_runtime_owner_stale(heartbeat_at: float | None, *, now: float | None = None) -> bool:
    if heartbeat_at is None:
        return True
    return ((now or time.time()) - heartbeat_at) > OWNER_HEARTBEAT_TIMEOUT_SECONDS


def is_session_read_only_for_runtime(
    *,
    current_runtime_id: str,
    current_runtime_has_actor: bool,
    session_state: SessionRuntimeState | str | None,
    runtime_owner: SessionOwner | None,
    runtime_owner_heartbeat_at: float | None,
) -> bool:
    if current_runtime_has_actor:
        return False
    if runtime_owner is None:
        return False
    if is_runtime_owner_stale(runtime_owner_heartbeat_at):
        return False
    if runtime_owner.runtime_id == current_runtime_id:
        return False
    if runtime_owner.runtime_kind == "tui":
        return True
    return session_state in _ACTIVE_SESSION_STATES


def is_session_read_only(
    *,
    state: WebAppState,
    session_id: str,
    session_state: SessionRuntimeState | str | None,
    runtime_owner: SessionOwner | None,
    runtime_owner_heartbeat_at: float | None,
) -> bool:
    return is_session_read_only_for_runtime(
        current_runtime_id=state.runtime.runtime_id,
        current_runtime_has_actor=state.runtime.session_registry.has_session_actor(session_id),
        session_state=session_state,
        runtime_owner=runtime_owner,
        runtime_owner_heartbeat_at=runtime_owner_heartbeat_at,
    )


def load_session_read_only(state: WebAppState, *, session_id: str, work_dir: Path) -> bool:
    session = Session.load_meta(session_id, work_dir=work_dir)
    return is_session_read_only(
        state=state,
        session_id=session_id,
        session_state=session.session_state,
        runtime_owner=session.runtime_owner,
        runtime_owner_heartbeat_at=session.runtime_owner_heartbeat_at,
    )
