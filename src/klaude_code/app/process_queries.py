"""Session snapshots shared by process IPC and persisted-history readers."""

from typing import Any

from klaude_code.app.session_state import derive_session_status
from klaude_code.app.session_view import (
    _brief_turn_activity,
    _last_assistant_text,
    _render_transcript_items,
    _render_turns,
)
from klaude_code.protocol.models.session_status import (
    SessionAttention,
    SessionContinuation,
    SessionOwnedTasks,
    SessionStatus,
    SessionTurnResult,
)
from klaude_code.session import Session


def persisted_status(session: Session) -> SessionStatus:
    active = session.runtime.active_turn
    return derive_session_status(
        session_id=session.id,
        facts=session.runtime,
        running=active is not None and active.started,
        queued=active is not None and not active.started,
        attention=[],
        continuation=SessionContinuation(),
        owned=SessionOwnedTasks(),
    )


def offline_status(session: Session) -> SessionStatus:
    facts = session.runtime.model_copy(deep=True)
    attention = []
    if facts.active_turn is not None:
        facts.last_turn = SessionTurnResult(id=facts.active_turn.id, result="interrupted", reason="process_exit")
        facts.active_turn = None
        attention.append(SessionAttention(kind="paused", code="process_exit", source_session_id=session.id))
    return derive_session_status(
        session_id=session.id,
        facts=facts,
        running=False,
        queued=False,
        attention=attention,
        continuation=SessionContinuation(),
        owned=SessionOwnedTasks(),
    )


def session_snapshot(
    session: Session,
    *,
    status: SessionStatus | None = None,
    pending: bool = False,
    turns: int | None = None,
    transcript: bool = False,
    summary_only: bool = False,
) -> dict[str, Any]:
    status = status or offline_status(session)
    result: dict[str, Any] = {
        "id": session.id,
        "session_id": session.id,
        "name": session.name,
        "group": session.group,
        "agent_type": session.agent_type,
        "spawn_kind": session.spawn_kind,
        "parent_session_id": session.parent_session_id,
        "state": status.category,
        "status": status.model_dump(mode="json"),
        "model": session.model_config_name or session.model_name,
        "work_dir": str(session.work_dir),
        "title": session.title,
        "messages_count": session.messages_count,
        "created_at": session.created_at,
        "updated_at": session.updated_at,
        "archived": session.archived,
        "activity": status.execution,
        "pending": pending,
        "todos": [item.model_dump(mode="json") for item in session.todos],
        "file_change_summary": session.file_change_summary.model_dump(mode="json"),
        "approval_policy": session.approval_policy,
    }
    if summary_only:
        return result
    history = session.conversation_history
    output = (
        "\n\n".join(_render_transcript_items(history))
        if transcript
        else _render_turns(history, turns)
        if turns is not None and turns > 0
        else _last_assistant_text(history)
    )
    activity = _brief_turn_activity(history)
    usage = session.last_request_usage
    result.update(
        {
            "output": output,
            **activity.model_dump(),
            "last_assistant_message": _last_assistant_text(history),
            "current_tool_call": None,
            "usage": usage.model_dump(mode="json") if usage is not None else None,
            "user_messages": session.user_messages,
            "user_message_count": len(session.user_messages),
        }
    )
    return result
