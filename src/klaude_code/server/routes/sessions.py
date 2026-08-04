from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Final, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from klaude_code.protocol import events as protocol_events
from klaude_code.protocol import op, user_interaction
from klaude_code.protocol.message import ImageFilePart, ImageURLPart, UserInputPayload
from klaude_code.server.session_index import (
    list_file_running_states,
    list_main_sessions,
    read_session_titles,
    read_session_user_messages,
    resolve_session_work_dir,
    search_sessions,
    soft_delete_session,
)
from klaude_code.server.session_live import format_sse_message
from klaude_code.server.session_state import derive_session_state_from_snapshot
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
_SERVER_STATE_DEP: Final = Depends(get_server_state)


def _runtime_session_states(state: ServerAppState) -> dict[str, Literal["idle", "running", "waiting_user_input"]]:
    return {
        snapshot.session_id: derive_session_state_from_snapshot(snapshot)
        for snapshot in state.runtime.session_registry.all_snapshots()
    }


class CreateSessionRequest(BaseModel):
    work_dir: str | None = None
    model: str | None = None
    vanilla: bool = False


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
    initial_search_text: str | None = None
    save_as_default: bool = False


@router.get("")
async def list_sessions(state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, list[dict[str, Any]]]:
    if state.session_live is None:
        raise RuntimeError("session live state is not initialized")
    state.session_live.index.reload()
    return {"groups": state.session_live.list_groups()}


@router.get("/search")
async def search_sessions_endpoint(
    q: str = "",
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, list[dict[str, Any]]]:
    """Search sessions by title, user messages, and workspace path."""
    results = search_sessions(state.home_dir, q)
    return {
        "results": [
            {
                "id": s.id,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "work_dir": s.work_dir,
                "title": s.title,
                "user_messages": s.user_messages,
                "archived": s.archived,
            }
            for s in results
        ]
    }


@router.get("/stream")
async def stream_sessions(request: Request, state: ServerAppState = _SERVER_STATE_DEP) -> StreamingResponse:
    if state.session_live is None:
        raise RuntimeError("session live state is not initialized")

    subscription = state.session_live.stream.subscribe()

    async def _next_event(iterator: AsyncIterator[Any]) -> Any:
        return await anext(iterator)

    async def _iter() -> AsyncIterator[str]:
        iterator = aiter(subscription)
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
    state: ServerAppState = _SERVER_STATE_DEP,
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
                "title": title_map.get(sid),
                "user_messages": user_messages_map.get(sid, []),
            }
            for sid, session_state in states.items()
        }
    }


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    target_work_dir = Path(payload.work_dir).expanduser() if payload.work_dir else state.work_dir
    if not target_work_dir.exists() or not target_work_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"work_dir does not exist: {target_work_dir}")
    target_work_dir = target_work_dir.resolve()

    if payload.model is not None:
        from klaude_code.config import load_config

        try:
            config = load_config()
            candidates = config.iter_model_config_candidates(payload.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown model '{payload.model}': {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to load config: {exc}") from exc
        if not candidates:
            raise HTTPException(status_code=400, detail=f"model '{payload.model}' is unavailable")

    # Persist meta first (model/vanilla are read when the agent is built),
    # then spin up the actor so follow-up REST/WS calls find it.
    session = Session.create(id=uuid4().hex, work_dir=target_work_dir)
    session.model_config_name = payload.model
    session.vanilla = payload.vanilla
    try:
        session.ensure_meta_exists()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session metadata: {exc}") from exc

    try:
        await state.runtime.submit_and_wait(
            op.InitAgentOperation(
                session_id=session.id,
                work_dir=target_work_dir,
                defer_welcome_context=True,
                defer_replay=True,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session: {exc}") from exc
    return {"session_id": session.id}


@router.post("/{session_id}/archive")
async def archive_session(session_id: str, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, bool]:
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
async def unarchive_session(session_id: str, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, bool]:
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")

    store = get_store_for_path(work_dir)
    unarchived = store.update_meta(session_id, {"archived": False})
    if not unarchived:
        raise HTTPException(status_code=500, detail="failed to unarchive session")
    return {"ok": True}


class ArchiveCleanupRequest(BaseModel):
    cutoff_seconds: int = 24 * 60 * 60


@router.post("/archive/cleanup")
async def cleanup_archived_sessions(
    payload: ArchiveCleanupRequest | None = None,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, bool | int]:
    cutoff_seconds = payload.cutoff_seconds if payload is not None else 24 * 60 * 60
    cutoff = time.time() - cutoff_seconds
    archived_count = 0

    for summary in list_main_sessions(state.home_dir):
        if summary.archived:
            continue
        if summary.session_state is not None and summary.session_state != "idle":
            continue

        diff_lines_added = cast(int, summary.file_change_summary.get("diff_lines_added", 0))
        diff_lines_removed = cast(int, summary.file_change_summary.get("diff_lines_removed", 0))
        has_no_diff = diff_lines_added == 0 and diff_lines_removed == 0
        if summary.updated_at >= cutoff and not has_no_diff:
            continue

        store = get_store_for_path(Path(summary.work_dir))
        archived = store.update_meta(summary.id, {"archived": True})
        if not archived:
            raise HTTPException(status_code=500, detail=f"failed to archive session: {summary.id}")

        archived_count += 1
        with contextlib.suppress(Exception):
            _ = await state.runtime.close_session(summary.id, force=True)

    return {"ok": True, "archived_count": archived_count}


@router.delete("/{session_id}")
async def delete_session(session_id: str, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, bool]:
    deleted = soft_delete_session(state.home_dir, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    if state.session_live is not None:
        state.session_live.apply_deleted(session_id)

    with contextlib.suppress(Exception):
        _ = await state.runtime.close_session(session_id, force=True)
    return {"ok": True}


@router.get("/{session_id}/history")
async def get_history(session_id: str, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")

    try:
        # Use the in-memory session only when it is ahead of disk (items
        # appended but not yet flushed by the background writer).  Otherwise
        # always prefer disk: the server
        # may initialise its own stale agent copy via InitAgentOperation and
        # that copy never receives further updates while the TUI keeps
        # appending to the real events file.
        disk_session = Session.load(session_id, work_dir=work_dir)
        runtime = state.runtime.session_registry.get_session_actor(session_id)
        agent = runtime.get_agent() if runtime is not None else None
        if agent is not None and len(agent.session.conversation_history) > len(disk_session.conversation_history):
            session = agent.session
        else:
            session = disk_session
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


def _check_write_access(state: ServerAppState, session_id: str) -> Path:
    """Validate the session exists; return its work_dir or raise 404."""
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")
    return work_dir


@router.post("/{session_id}/message")
async def post_message(
    session_id: str,
    payload: MessageRequest,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    _check_write_access(state, session_id)

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
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    _check_write_access(state, session_id)
    operation_id = await state.runtime.submit(op.InterruptOperation(session_id=session_id))
    return {"operation_id": operation_id}


@router.post("/{session_id}/respond")
async def respond_interaction(
    session_id: str,
    payload: RespondRequest,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, bool]:
    _check_write_access(state, session_id)
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
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    _check_write_access(state, session_id)
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
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    _check_write_access(state, session_id)
    operation_id = await state.runtime.submit(
        op.RequestModelOperation(
            session_id=session_id,
            initial_search_text=payload.initial_search_text,
            save_as_default=payload.save_as_default,
        )
    )
    return {"operation_id": operation_id}
