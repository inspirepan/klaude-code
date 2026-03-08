from __future__ import annotations

import time
from pathlib import Path

from klaude_code.protocol import model
from klaude_code.session.session import Session
from klaude_code.web.state import WebAppState

OWNER_HEARTBEAT_TIMEOUT_SECONDS = 15.0


def is_runtime_owner_stale(heartbeat_at: float | None, *, now: float | None = None) -> bool:
    if heartbeat_at is None:
        return True
    return ((now or time.time()) - heartbeat_at) > OWNER_HEARTBEAT_TIMEOUT_SECONDS


def is_session_read_only(
    *,
    state: WebAppState,
    session_id: str,
    session_state: model.SessionRuntimeState | str | None,
    runtime_owner: model.SessionOwner | None,
    runtime_owner_heartbeat_at: float | None,
) -> bool:
    if state.runtime.session_registry.has_session_actor(session_id):
        return False
    if session_state not in (
        model.SessionRuntimeState.RUNNING,
        model.SessionRuntimeState.WAITING_USER_INPUT,
        "running",
        "waiting_user_input",
    ):
        return False
    if runtime_owner is None:
        return False
    if is_runtime_owner_stale(runtime_owner_heartbeat_at):
        return False
    return runtime_owner.runtime_id != state.runtime.runtime_id


def load_session_read_only(state: WebAppState, *, session_id: str, work_dir: Path) -> bool:
    session = Session.load_meta(session_id, work_dir=work_dir)
    return is_session_read_only(
        state=state,
        session_id=session_id,
        session_state=session.session_state,
        runtime_owner=session.runtime_owner,
        runtime_owner_heartbeat_at=session.runtime_owner_heartbeat_at,
    )
