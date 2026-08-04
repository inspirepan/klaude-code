"""Single source of truth for deriving a session's runtime state.

The actor snapshot is authoritative in the single-server model. This helper
replaces the three former copies in routes/server.py, routes/sessions.py, and
session_live.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from klaude_code.control.runtime.actor import SessionActorSnapshot
from klaude_code.protocol.models import SessionRuntimeState

if TYPE_CHECKING:
    from klaude_code.control.runtime.registry import SessionRegistry

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


def live_descendant_session_ids(registry: SessionRegistry, session_id: str) -> set[str]:
    """Session ids of in-memory sub-agent sessions spawned under this session."""
    by_parent: dict[str, list[str]] = {}
    for actor in registry.list_session_actors():
        agent = actor.get_agent()
        parent = agent.session.parent_session_id if agent is not None else None
        if parent:
            by_parent.setdefault(parent, []).append(actor.session_id)
    result: set[str] = set()
    queue = [session_id]
    while queue:
        current = queue.pop()
        for child in by_parent.get(current, ()):
            if child not in result:
                result.add(child)
                queue.append(child)
    return result
