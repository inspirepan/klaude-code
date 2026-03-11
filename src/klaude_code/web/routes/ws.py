from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
from concurrent.futures import CancelledError as FutureCancelledError
from pathlib import Path
from typing import Any, Literal, cast
from uuid import uuid4

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from klaude_code.protocol import events, llm_param, message, model, op, user_interaction
from klaude_code.protocol.message import ImageFilePart, ImageURLPart, UserInputPayload
from klaude_code.session.session import Session, get_store_for_path
from klaude_code.web.session_access import load_session_read_only
from klaude_code.web.session_index import resolve_session_work_dir
from klaude_code.web.state import get_web_state_from_ws

router = APIRouter(tags=["websocket"])


class MessageFrame(BaseModel):
    type: Literal["message"]
    text: str = ""
    images: list[ImageURLPart | ImageFilePart] | None = None


class InterruptFrame(BaseModel):
    type: Literal["interrupt"]


class RespondFrame(BaseModel):
    type: Literal["respond"]
    request_id: str
    status: Literal["submitted", "cancelled"]
    payload: user_interaction.UserInteractionResponsePayload | None = None


class ContinueFrame(BaseModel):
    type: Literal["continue"]


class ModelFrame(BaseModel):
    type: Literal["model"]
    model_name: str
    save_as_default: bool = False


class RequestModelFrame(BaseModel):
    type: Literal["model_request"]
    preferred: str | None = None
    save_as_default: bool = False


class ThinkingFrame(BaseModel):
    type: Literal["thinking"]
    thinking: llm_param.Thinking


type IncomingFrame = (
    MessageFrame
    | InterruptFrame
    | RespondFrame
    | ContinueFrame
    | ModelFrame
    | RequestModelFrame
    | ThinkingFrame
)


async def _send_error_frame(
    websocket: WebSocket,
    *,
    code: str,
    message: str,
    detail: Any = None,
) -> None:
    await websocket.send_json(
        {
            "type": "error",
            "code": code,
            "message": message,
            "detail": detail,
        }
    )


def _extract_usage_from_history(history: list[message.HistoryEvent]) -> model.Usage | None:
    for item in reversed(history):
        if isinstance(item, model.TaskMetadataItem) and item.main_agent.usage is not None:
            return item.main_agent.usage
        if isinstance(item, message.AssistantMessage) and item.usage is not None:
            return item.usage
    return None


def _load_usage_snapshot(session_id: str, session_work_dir: Path, websocket: WebSocket) -> dict[str, Any]:
    usage = model.Usage()
    state = get_web_state_from_ws(websocket)

    current_agent = state.runtime.current_agent
    if current_agent is not None and current_agent.session.id == session_id:
        in_memory_usage = _extract_usage_from_history(current_agent.session.conversation_history)
        if in_memory_usage is not None:
            usage = in_memory_usage

    try:
        session = Session.load(session_id, work_dir=session_work_dir)
        disk_usage = _extract_usage_from_history(session.conversation_history)
        if disk_usage is not None:
            usage = disk_usage
    except Exception:
        pass

    return {
        "event_type": "usage.snapshot",
        "session_id": session_id,
        "event": {"usage": usage.model_dump(mode="json")},
        "timestamp": time.time(),
    }


async def _handle_incoming_frame(
    session_id: str,
    frame: IncomingFrame,
    websocket: WebSocket,
    *,
    is_holder: bool,
) -> None:
    state = get_web_state_from_ws(websocket)
    runtime = state.runtime
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        await _send_error_frame(websocket, code="session_not_found", message=f"Session not found: {session_id}")
        return
    if load_session_read_only(state, session_id=session_id, work_dir=work_dir):
        await _send_error_frame(
            websocket,
            code="session_read_only",
            message="Session is owned by another runtime and is read-only",
        )
        return

    if not is_holder:
        await _send_error_frame(
            websocket,
            code="session_not_held",
            message="Session is held by another connection",
        )
        return

    try:
        if isinstance(frame, MessageFrame):
            await runtime.emit_event(
                events.UserMessageEvent(content=frame.text, session_id=session_id, images=frame.images)
            )
            await runtime.submit(
                op.RunAgentOperation(
                    session_id=session_id,
                    input=UserInputPayload(text=frame.text, images=frame.images),
                )
            )
            return

        if isinstance(frame, InterruptFrame):
            await runtime.submit(op.InterruptOperation(session_id=session_id))
            return

        if isinstance(frame, RespondFrame):
            await runtime.submit(
                op.UserInteractionRespondOperation(
                    session_id=session_id,
                    request_id=frame.request_id,
                    response=user_interaction.UserInteractionResponse(status=frame.status, payload=frame.payload),
                )
            )
            return

        if isinstance(frame, ContinueFrame):
            await runtime.submit(op.ContinueAgentOperation(session_id=session_id))
            return

        if isinstance(frame, ModelFrame):
            await runtime.submit(
                op.ChangeModelOperation(
                    session_id=session_id,
                    model_name=frame.model_name,
                    save_as_default=frame.save_as_default,
                )
            )
            return

        if isinstance(frame, RequestModelFrame):
            await runtime.submit(
                op.RequestModelOperation(
                    session_id=session_id,
                    preferred=frame.preferred,
                    save_as_default=frame.save_as_default,
                )
            )
            return

        await runtime.submit(
            op.ChangeThinkingOperation(
                session_id=session_id,
                thinking=frame.thinking,
            )
        )
        return
    except Exception as exc:
        if isinstance(exc, FutureCancelledError):
            return
        await _send_error_frame(
            websocket,
            code="invalid_payload",
            message=f"Failed to handle message: {exc}",
        )


def _validate_incoming_frame(payload: dict[str, Any], frame_type: str) -> IncomingFrame:
    if frame_type == "message":
        return MessageFrame.model_validate(payload)
    if frame_type == "interrupt":
        return InterruptFrame.model_validate(payload)
    if frame_type == "respond":
        return RespondFrame.model_validate(payload)
    if frame_type == "continue":
        return ContinueFrame.model_validate(payload)
    if frame_type == "model":
        return ModelFrame.model_validate(payload)
    if frame_type == "model_request":
        return RequestModelFrame.model_validate(payload)
    return ThinkingFrame.model_validate(payload)


async def _forward_events(session_id: str, websocket: WebSocket) -> None:
    state = get_web_state_from_ws(websocket)
    subscription = state.subscribe_events(None)
    tracked_task_ids: set[str] = set()

    snapshot = state.runtime.session_registry.snapshot(session_id)
    if snapshot is not None and snapshot.active_root_task is not None:
        tracked_task_ids.add(snapshot.active_root_task.task_id)

    try:
        async for envelope in subscription:
            if envelope.session_id == session_id:
                if envelope.task_id is not None:
                    tracked_task_ids.add(envelope.task_id)
            elif envelope.task_id not in tracked_task_ids:
                continue

            await websocket.send_json(envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True))
    except (WebSocketDisconnect, RuntimeError, anyio.ClosedResourceError, asyncio.CancelledError, FutureCancelledError):
        return


async def _receive_commands(
    session_id: str,
    websocket: WebSocket,
    *,
    is_holder: bool = False,
) -> None:
    background_submits: set[asyncio.Task[None]] = set()
    while True:
        try:
            payload = await websocket.receive_json()
        except (WebSocketDisconnect, anyio.ClosedResourceError, asyncio.CancelledError, FutureCancelledError):
            return
        except Exception:
            with contextlib.suppress(Exception):
                await _send_error_frame(websocket, code="invalid_message", message="Message must be valid JSON")
            continue

        if not isinstance(payload, dict):
            await _send_error_frame(websocket, code="invalid_message", message="Message must be an object")
            continue
        payload_dict = cast(dict[str, Any], payload)

        frame_type_raw = payload_dict.get("type")
        if not isinstance(frame_type_raw, str):
            await _send_error_frame(websocket, code="invalid_message", message="Missing message type")
            continue
        frame_type = frame_type_raw
        if frame_type not in {
            "message",
            "interrupt",
            "respond",
            "continue",
            "model",
            "model_request",
            "thinking",
        }:
            await _send_error_frame(websocket, code="unknown_type", message=f"Unknown message type: {frame_type}")
            continue

        try:
            frame = _validate_incoming_frame(payload_dict, frame_type)
        except ValidationError as exc:
            await _send_error_frame(
                websocket,
                code="invalid_payload",
                message="Invalid payload",
                detail=exc.errors(),
            )
            continue

        if isinstance(frame, InterruptFrame):
            submit_task = asyncio.create_task(_handle_incoming_frame(session_id, frame, websocket, is_holder=is_holder))
            background_submits.add(submit_task)
            submit_task.add_done_callback(background_submits.discard)
            continue

        await _handle_incoming_frame(session_id, frame, websocket, is_holder=is_holder)


@router.websocket("/api/sessions/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    send_task: asyncio.Task[None] | None = None
    recv_task: asyncio.Task[None] | None = None
    holder_key: str | None = None
    is_holder = False
    try:
        await websocket.accept()
        state = get_web_state_from_ws(websocket)
        work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if work_dir is None:
            await _send_error_frame(websocket, code="session_not_found", message=f"Session not found: {session_id}")
            await websocket.close(code=4004)
            return

        read_only = load_session_read_only(state, session_id=session_id, work_dir=work_dir)
        if not state.runtime.session_registry.has_session_actor(session_id) and not read_only:
            try:
                await state.runtime.submit_and_wait(op.InitAgentOperation(session_id=session_id, work_dir=work_dir))
            except Exception as exc:
                await _send_error_frame(
                    websocket,
                    code="session_init_failed",
                    message=f"Failed to initialize session: {exc}",
                )
                await websocket.close(code=4005)
                return

        # Resolve holder key: accept from query param or generate a new one.
        raw_key = websocket.query_params.get("holder_key")
        holder_key = raw_key.strip() if raw_key else uuid4().hex

        if not read_only:
            is_holder = await state.runtime.try_acquire_holder(session_id, holder_key)

        # Send connection info frame with holder status.
        await websocket.send_json(
            {
                "type": "connection_info",
                "is_holder": is_holder,
                "session_id": session_id,
            }
        )

        await websocket.send_json(_load_usage_snapshot(session_id, work_dir, websocket))

        send_task = asyncio.create_task(_forward_events(session_id, websocket))
        recv_task = asyncio.create_task(_receive_commands(session_id, websocket, is_holder=is_holder))
        done, pending = await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)

        if pending:
            for task in pending:
                task.cancel()
            _ = await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            with contextlib.suppress(asyncio.CancelledError, FutureCancelledError):
                exc = task.exception()
                if exc is None:
                    continue
                if isinstance(exc, WebSocketDisconnect):
                    continue
                raise exc
    except (WebSocketDisconnect, asyncio.CancelledError, FutureCancelledError):
        return
    finally:
        # Release holder on disconnect (starts grace period).
        if is_holder and holder_key is not None:
            state = get_web_state_from_ws(websocket)
            with contextlib.suppress(Exception):
                await state.runtime.release_holder(session_id, holder_key)

            with contextlib.suppress(Exception):
                registry = cast(Any, state.runtime.session_registry)
                if not hasattr(registry, "get_session_actor"):
                    raise RuntimeError
                runtime = registry.get_session_actor(session_id)
                agent = runtime.get_agent() if runtime is not None else None
                if agent is not None:
                    if agent.session.messages_count != 0:
                        raise RuntimeError
                    with contextlib.suppress(Exception):
                        _ = await state.runtime.close_session(session_id, force=True)
                    shutil.rmtree(Session.paths(agent.session.work_dir).session_dir(session_id), ignore_errors=True)
                else:
                    work_dir = resolve_session_work_dir(state.home_dir, session_id)
                    if work_dir is None:
                        raise RuntimeError
                    raw_meta = get_store_for_path(work_dir).load_meta(session_id)
                    if raw_meta is None:
                        raise RuntimeError
                    messages_count = int(raw_meta.get("messages_count", -1))
                    if messages_count != 0:
                        raise RuntimeError
                    shutil.rmtree(Session.paths(work_dir).session_dir(session_id), ignore_errors=True)

        tasks_to_cancel = [task for task in (send_task, recv_task) if task is not None and not task.done()]
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            _ = await asyncio.gather(*tasks_to_cancel, return_exceptions=True)
