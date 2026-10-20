"""Derive public session status separately from internal actor activity.

Public status combines scheduler, task, and interaction facts. The actor-only
activity helper remains for operational blockers and sleep prevention.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, cast

from klaude_code.control.runtime.actor import SessionActorSnapshot
from klaude_code.protocol.models import SessionRuntimeState
from klaude_code.protocol.models.session_status import (
    SessionAttention,
    SessionContinuation,
    SessionOwnedTasks,
    SessionRuntimeFacts,
    SessionStatus,
)

if TYPE_CHECKING:
    from klaude_code.control.runtime.registry import SessionRegistry

type RuntimeStateLiteral = Literal["idle", "running", "waiting_user_input"]


def derive_session_status(
    *,
    session_id: str,
    facts: SessionRuntimeFacts,
    running: bool,
    queued: bool,
    attention: list[SessionAttention],
    continuation: SessionContinuation,
    owned: SessionOwnedTasks,
) -> SessionStatus:
    attention = list(attention)
    if facts.error is not None:
        attention.append(
            SessionAttention(
                kind="error", code=facts.error.code, source_session_id=session_id, message=facts.error.message
            )
        )
    if continuation.blocked_by and continuation.triggers and continuation.blocked_by[0] != "execution_failed":
        attention.append(SessionAttention(kind="paused", code=continuation.blocked_by[0], source_session_id=session_id))
    execution: Literal["none", "queued", "running", "waiting_agents"] = "none"
    if running:
        execution = "running"
    elif queued and continuation.automatic:
        execution = "queued"
    elif continuation.automatic:
        execution = "waiting_agents" if "agent_result" in continuation.triggers else "queued"
    category: Literal["needs_you", "working", "idle"] = "idle"
    if attention:
        category = "needs_you"
    elif execution != "none":
        category = "working"
    return SessionStatus(
        category=category,
        execution=execution,
        attention=attention,
        control=facts.control.model_copy(deep=True),
        continuation=continuation,
        last_turn=facts.last_turn,
        owned=owned,
    )


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
