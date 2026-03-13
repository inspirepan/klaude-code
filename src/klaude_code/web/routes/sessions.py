from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from klaude_code.protocol import events as protocol_events
from klaude_code.protocol import model as protocol_model
from klaude_code.protocol import op, user_interaction
from klaude_code.protocol.message import ImageFilePart, ImageURLPart, UserInputPayload
from klaude_code.session.session import Session, get_store_for_path
from klaude_code.web.session_access import load_session_read_only
from klaude_code.web.session_index import (
    list_file_running_states,
    read_session_titles,
    read_session_user_messages,
    resolve_session_work_dir,
    soft_delete_session,
)
from klaude_code.web.session_live import format_sse_message
from klaude_code.web.state import WebAppState, get_web_state

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
WEB_STATE_DEP: Final = Depends(get_web_state)
SESSION_STATE_IDLE: Final = cast(
    Literal["idle", "running", "waiting_user_input"], protocol_model.SessionRuntimeState.IDLE.value
)


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


class RequestModelRequest(BaseModel):
    preferred: str | None = None
    save_as_default: bool = False


@router.get("")
async def list_sessions(state: WebAppState = WEB_STATE_DEP) -> dict[str, list[dict[str, Any]]]:
    if state.session_live is None:
        raise RuntimeError("session live state is not initialized")
    state.session_live.index.reload()
    return {"groups": state.session_live.list_groups()}


@router.get("/stream")
async def stream_sessions(request: Request, state: WebAppState = WEB_STATE_DEP) -> StreamingResponse:
    if state.session_live is None:
        raise RuntimeError("session live state is not initialized")

    subscription = state.session_live.stream.subscribe()

    async def _next_event(iterator: AsyncIterator[Any]) -> Any:
        return await anext(iterator)

    async def _iter() -> AsyncIterator[str]:
        iterator = subscription.__aiter__()
        next_event_task: asyncio.Task[Any] | None = None
        try:
            while True:
                if next_event_task is None:
                    next_event_task = asyncio.create_task(_next_event(iterator))
                try:
                    done, _ = await asyncio.wait({next_event_task}, timeout=10.0)
                    if not done:
                        if await request.is_disconnected():
                            break
                        yield ": keepalive\n\n"
                        continue
                    event = next_event_task.result()
                except StopAsyncIteration:
                    break
                if await request.is_disconnected():
                    break
                next_event_task = None
                yield format_sse_message(event)
        finally:
            if next_event_task is not None and not next_event_task.done():
                next_event_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await next_event_task

    return StreamingResponse(
        _iter(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/running")
async def list_running_sessions(
    state: WebAppState = WEB_STATE_DEP,
) -> dict[str, dict[str, Any]]:
    """Return runtime states for sessions that have active actors."""
    runtime_states = _runtime_session_states(state)
    states: dict[str, str] = {
        session_id: session_state
        for session_id, session_state in runtime_states.items()
        if session_state in ("running", "waiting_user_input")
    }
    for sid, file_state in list_file_running_states(state.home_dir).items():
        if sid not in states:
            states[sid] = file_state
    session_ids = set(states.keys())
    user_messages_map = read_session_user_messages(state.home_dir, session_ids)
    title_map = read_session_titles(state.home_dir, session_ids)
    return {
        "states": {
            sid: {
                "session_state": session_state,
                "read_only": load_session_read_only(
                    state,
                    session_id=sid,
                    work_dir=resolve_session_work_dir(state.home_dir, sid) or state.work_dir,
                ),
                "title": title_map.get(sid),
                "user_messages": user_messages_map.get(sid, []),
            }
            for sid, session_state in states.items()
        }
    }


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
        await state.runtime.submit_and_wait(
            op.InitAgentOperation(session_id=session_id, work_dir=target_work_dir.resolve())
        )
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
            "title": None,
            "sub_agent_state": None,
            "created_at": now,
            "updated_at": now,
            "user_messages": [],
            "messages_count": 0,
            "model_name": current_model_name,
            "session_state": "idle",
            "runtime_owner": state.runtime.session_owner.model_dump(mode="json"),
            "runtime_owner_heartbeat_at": time.time(),
            "archived": False,
            "todos": [],
            "file_change_summary": {
                "created_files": [],
                "edited_files": [],
                "diff_lines_added": 0,
                "diff_lines_removed": 0,
                "file_diffs": {},
            },
        }
        if not store.create_meta_if_missing(session_id, meta):
            raise HTTPException(status_code=500, detail="failed to create session metadata")
    return {"session_id": session_id}


@router.post("/{session_id}/archive")
async def archive_session(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, bool]:
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")

    store = get_store_for_path(work_dir)
    archived = store.update_meta(session_id, {"archived": True})
    if not archived:
        raise HTTPException(status_code=500, detail="failed to archive session")

    with contextlib.suppress(Exception):
        _ = await state.runtime.close_session(session_id, force=True)
    return {"ok": True}


@router.post("/{session_id}/unarchive")
async def unarchive_session(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, bool]:
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")

    store = get_store_for_path(work_dir)
    unarchived = store.update_meta(session_id, {"archived": False})
    if not unarchived:
        raise HTTPException(status_code=500, detail="failed to unarchive session")
    return {"ok": True}


@router.delete("/{session_id}")
async def delete_session(session_id: str, state: WebAppState = WEB_STATE_DEP) -> dict[str, bool]:
    deleted = soft_delete_session(state.home_dir, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    if state.session_live is not None:
        state.session_live.apply_deleted(session_id)

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


def _check_write_access(state: WebAppState, session_id: str, holder_key: str | None) -> Path:
    """Validate session exists, is not read-only, and caller holds the session lock (if one exists).

    Returns the session work_dir on success; raises HTTPException otherwise.
    """
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")
    if load_session_read_only(state, session_id=session_id, work_dir=work_dir):
        raise HTTPException(status_code=409, detail="session is owned by another runtime and is read-only")
    # If a holder is active on this session, the caller must provide the matching key.
    if state.runtime.holder_is_active(session_id) and (
        holder_key is None or not state.runtime.is_held_by(session_id, holder_key)
    ):
        raise HTTPException(status_code=409, detail="session is held by another connection")
    return work_dir


@router.post("/{session_id}/message")
async def post_message(
    session_id: str,
    payload: MessageRequest,
    state: WebAppState = WEB_STATE_DEP,
    x_holder_key: str | None = Header(None),
) -> dict[str, str]:
    _check_write_access(state, session_id, x_holder_key)

    await state.runtime.emit_event(
        protocol_events.UserMessageEvent(content=payload.text, session_id=session_id, images=payload.images)
    )

    operation_id = await state.runtime.submit(
        op.RunAgentOperation(
            session_id=session_id,
            input=UserInputPayload(text=payload.text, images=payload.images),
        )
    )
    return {"operation_id": operation_id}


@router.post("/{session_id}/interrupt")
async def interrupt_session(
    session_id: str,
    state: WebAppState = WEB_STATE_DEP,
    x_holder_key: str | None = Header(None),
) -> dict[str, str]:
    _check_write_access(state, session_id, x_holder_key)
    operation_id = await state.runtime.submit(op.InterruptOperation(session_id=session_id))
    return {"operation_id": operation_id}


@router.post("/{session_id}/respond")
async def respond_interaction(
    session_id: str,
    payload: RespondRequest,
    state: WebAppState = WEB_STATE_DEP,
    x_holder_key: str | None = Header(None),
) -> dict[str, bool]:
    _check_write_access(state, session_id, x_holder_key)
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
    x_holder_key: str | None = Header(None),
) -> dict[str, str]:
    _check_write_access(state, session_id, x_holder_key)
    operation_id = await state.runtime.submit(
        op.ChangeModelOperation(
            session_id=session_id,
            model_name=payload.model_name,
            save_as_default=payload.save_as_default,
        )
    )
    return {"operation_id": operation_id}


@router.post("/{session_id}/model/request")
async def request_model(
    session_id: str,
    payload: RequestModelRequest,
    state: WebAppState = WEB_STATE_DEP,
    x_holder_key: str | None = Header(None),
) -> dict[str, str]:
    _check_write_access(state, session_id, x_holder_key)
    operation_id = await state.runtime.submit(
        op.RequestModelOperation(
            session_id=session_id,
            preferred=payload.preferred,
            save_as_default=payload.save_as_default,
        )
    )
    return {"operation_id": operation_id}
