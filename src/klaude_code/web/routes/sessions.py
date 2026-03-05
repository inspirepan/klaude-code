from __future__ import annotations

import contextlib
import json
import time
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from klaude_code.protocol import events as protocol_events
from klaude_code.protocol import model as protocol_model
from klaude_code.protocol import op, user_interaction
from klaude_code.protocol.message import ImageFilePart, ImageURLPart, UserInputPayload
from klaude_code.session.session import Session, get_store_for_path
from klaude_code.web.session_index import (
    list_main_sessions,
    resolve_session_work_dir,
    soft_delete_session,
)
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
WEB_STATE_DEP: Final = Depends(get_web_state)
SESSION_STATE_IDLE: Final = cast(Literal["idle", "running", "waiting_user_input"], protocol_model.SessionRuntimeState.IDLE.value)


def _derive_session_state_from_snapshot(snapshot: Any) -> Literal["idle", "running", "waiting_user_input"]:
    if snapshot.pending_request_count > 0:
        return cast(
            Literal["idle", "running", "waiting_user_input"],
            protocol_model.SessionRuntimeState.WAITING_USER_INPUT.value,
        )
    if snapshot.active_root_task is not None or snapshot.child_task_count > 0:
        return cast(
            Literal["idle", "running", "waiting_user_input"],
            protocol_model.SessionRuntimeState.RUNNING.value,
        )
    return SESSION_STATE_IDLE


def _runtime_session_states(state: WebAppState) -> dict[str, Literal["idle", "running", "waiting_user_input"]]:
    return {
        snapshot.session_id: _derive_session_state_from_snapshot(snapshot)
        for snapshot in state.runtime.session_registry.all_snapshots()
    }


class CreateSessionRequest(BaseModel):
    work_dir: str | None = None


class MessageRequest(BaseModel):
    text: str = ""
    images: list[ImageURLPart | ImageFilePart] | None = None


class RespondRequest(BaseModel):
    request_id: str
    status: Literal["submitted", "cancelled"]
    payload: user_interaction.UserInteractionResponsePayload | None = None


class ModelRequest(BaseModel):
    model_name: str
    save_as_default: bool = False


@router.get("")
async def list_sessions(state: WebAppState = WEB_STATE_DEP) -> dict[str, list[dict[str, Any]]]:
    groups_by_work_dir: dict[str, list[dict[str, Any]]] = {}
    runtime_states = _runtime_session_states(state)
    for item in list_main_sessions(state.home_dir):
        session_state = runtime_states.get(item.id, item.session_state or SESSION_STATE_IDLE)
        groups_by_work_dir.setdefault(item.work_dir, []).append(
            {
                "id": item.id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "work_dir": item.work_dir,
                "user_messages": item.user_messages,
                "messages_count": item.messages_count,
                "model_name": item.model_name,
                "session_state": session_state,
            }
        )
    groups = [{"work_dir": work_dir, "sessions": sessions} for work_dir, sessions in groups_by_work_dir.items()]
    return {"groups": groups}


@router.get("/running")
async def list_running_sessions(
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, dict[str, str]]:
    """Return runtime states for sessions that have active actors."""
    states: dict[str, str] = dict(_runtime_session_states(state))
    return {"states": states}


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, str]:
    target_work_dir = Path(payload.work_dir).expanduser() if payload.work_dir else state.work_dir
    if not target_work_dir.exists() or not target_work_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"work_dir does not exist: {target_work_dir}")

    session_id = uuid4().hex
    try:
        await state.runtime.submit_and_wait(op.InitAgentOperation(session_id=session_id, work_dir=target_work_dir.resolve()))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session: {exc}") from exc

    store = get_store_for_path(target_work_dir.resolve())
    meta_path = store.paths.meta_file(session_id)
    if not meta_path.exists():
        now = time.time()
        current_agent = state.runtime.current_agent
        current_model_name = (
            current_agent.session.model_name
            if current_agent is not None and current_agent.session.id == session_id
            else None
        )
        meta: dict[str, Any] = {
            "id": session_id,
            "work_dir": str(target_work_dir.resolve()),
            "sub_agent_state": None,
            "created_at": now,
            "updated_at": now,
            "user_messages": [],
            "messages_count": 0,
            "model_name": current_model_name,
            "session_state": "idle",
        }
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"session_id": session_id}


@router.delete("/{session_id}")
async def delete_session(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, bool]:
    deleted = soft_delete_session(state.home_dir, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")

    with contextlib.suppress(Exception):
        _ = await state.runtime.close_session(session_id, force=True)
    return {"ok": True}


@router.get("/{session_id}/history")
async def get_history(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, Any]:
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")

    try:
        session = Session.load(session_id, work_dir=work_dir)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to load session history: {exc}") from exc

    payload = [
        {
            "event_type": protocol_events.event_type_name(event),
            "timestamp": event.timestamp,
            "event": event.model_dump(mode="json", exclude_none=True, serialize_as_any=True),
        }
        for event in session.get_history_item()
    ]
    return {"session_id": session_id, "events": payload}


@router.post("/{session_id}/message")
async def post_message(
    session_id: str,
    payload: MessageRequest,
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, str]:
    if resolve_session_work_dir(state.home_dir, session_id) is None:
        raise HTTPException(status_code=404, detail="session not found")

    operation_id = await state.runtime.submit(
        op.RunAgentOperation(
            session_id=session_id,
            input=UserInputPayload(text=payload.text, images=payload.images),
        )
    )
    return {"operation_id": operation_id}


@router.post("/{session_id}/interrupt")
async def interrupt_session(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, str]:
    operation_id = await state.runtime.submit(op.InterruptOperation(session_id=session_id))
    return {"operation_id": operation_id}


@router.post("/{session_id}/respond")
async def respond_interaction(
    session_id: str,
    payload: RespondRequest,
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, bool]:
    await state.runtime.submit(
        op.UserInteractionRespondOperation(
            session_id=session_id,
            request_id=payload.request_id,
            response=user_interaction.UserInteractionResponse(status=payload.status, payload=payload.payload),
        )
    )
    return {"ok": True}


@router.post("/{session_id}/model")
async def change_model(
    session_id: str,
    payload: ModelRequest,
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, str]:
    operation_id = await state.runtime.submit(
        op.ChangeModelOperation(
            session_id=session_id,
            model_name=payload.model_name,
            save_as_default=payload.save_as_default,
        )
    )
    return {"operation_id": operation_id}
