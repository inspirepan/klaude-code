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

from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
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


class CompactFrame(BaseModel):
    type: Literal["compact"]
    focus: str | None = None


type IncomingFrame = (
    MessageFrame
    | InterruptFrame
    | RespondFrame
    | ContinueFrame
    | ModelFrame
    | RequestModelFrame
    | ThinkingFrame
    | CompactFrame
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

        if isinstance(frame, ThinkingFrame):
            await runtime.submit(
                op.ChangeThinkingOperation(
                    session_id=session_id,
                    thinking=frame.thinking,
                )
            )
            return

        await runtime.submit(
            op.CompactSessionOperation(
                session_id=session_id,
                reason="manual",
                focus=frame.focus,
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
    if frame_type == "thinking":
        return ThinkingFrame.model_validate(payload)
    return CompactFrame.model_validate(payload)


def _collect_descendant_session_ids(session_id: str, work_dir: Path) -> set[str]:
    """Collect all descendant sub-agent session IDs by scanning session histories.

    Uses BFS to find SpawnSubAgentEntry items in the parent session and recurse
    into child sessions.  This is needed when there is no in-memory session
    snapshot (e.g. viewing a TUI-owned session from the web) so that sub-agent
    events can be forwarded via session-id matching.
    """
    result: set[str] = set()
    queue = [session_id]
    visited: set[str] = {session_id}
    store = get_store_for_path(work_dir)
    while queue:
        current_id = queue.pop(0)
        try:
            history = store.load_history(current_id)
        except Exception:
            continue
        for item in history:
            if isinstance(item, message.SpawnSubAgentEntry):
                child_id = item.session_id
                if child_id not in visited:
                    visited.add(child_id)
                    result.add(child_id)
                    queue.append(child_id)
    return result


_BATCH_WINDOW_SECONDS = 0.005  # 5ms — imperceptible for text streaming, good batching during bursts
_BATCH_MAX_SIZE = 50


async def _forward_events(session_id: str, websocket: WebSocket) -> None:
    state = get_web_state_from_ws(websocket)
    subscription = state.subscribe_events(None)
    tracked_task_ids: set[str] = set()
    tracked_child_session_ids: set[str] = set()

    snapshot = state.runtime.session_registry.snapshot(session_id)
    if snapshot is not None and snapshot.active_root_task is not None:
        tracked_task_ids.add(snapshot.active_root_task.task_id)

    # When there is no active root task tracked (e.g. viewing a TUI-owned session
    # or reconnecting after a server restart), scan the persisted history for
    # sub-agent sessions so their real-time events are forwarded to this WebSocket.
    if not tracked_task_ids:
        work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if work_dir is not None:
            tracked_child_session_ids = _collect_descendant_session_ids(session_id, work_dir)
            if tracked_child_session_ids:
                log_debug(
                    f"[web/ws:{session_id[:8]}] tracked {len(tracked_child_session_ids)} descendant session(s) from history",
                    debug_type=DebugType.EXECUTION,
                )

    send_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=512)

    async def _read_events() -> None:
        try:
            async for envelope in subscription:
                if envelope.session_id == session_id or envelope.session_id in tracked_child_session_ids:
                    if envelope.task_id is not None:
                        tracked_task_ids.add(envelope.task_id)
                elif envelope.task_id not in tracked_task_ids:
                    continue

                serialized = envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True)
                await send_queue.put(serialized)
        except (
            WebSocketDisconnect, RuntimeError, anyio.ClosedResourceError,
            asyncio.CancelledError, FutureCancelledError,
        ):
            return

    async def _send_batched() -> None:
        try:
            while True:
                first = await send_queue.get()
                batch = [first]
                # Yield to let the reader enqueue more events that arrived in the same burst.
                await asyncio.sleep(_BATCH_WINDOW_SECONDS)
                while len(batch) < _BATCH_MAX_SIZE:
                    try:
                        batch.append(send_queue.get_nowait())
                    except asyncio.QueueEmpty:
                        break
                if len(batch) == 1:
                    await websocket.send_json(batch[0])
                else:
                    await websocket.send_json(batch)
        except (
            WebSocketDisconnect, RuntimeError, anyio.ClosedResourceError,
            asyncio.CancelledError, FutureCancelledError,
        ):
            return

    read_task = asyncio.create_task(_read_events())
    send_task = asyncio.create_task(_send_batched())
    try:
        await asyncio.wait({read_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in (read_task, send_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(read_task, send_task, return_exceptions=True)


async def _send_pending_interaction_snapshots(session_id: str, websocket: WebSocket) -> None:
    state = get_web_state_from_ws(websocket)
    get_session_actor = getattr(state.runtime.session_registry, "get_session_actor", None)
    if not callable(get_session_actor):
        return
    runtime = get_session_actor(session_id)
    if runtime is None:
        return

    pending_requests_snapshot = getattr(runtime, "pending_requests_snapshot", None)
    if not callable(pending_requests_snapshot):
        return

    requests = cast(list[PendingUserInteractionRequest], pending_requests_snapshot())
    for request in requests:
        timestamp = time.time()
        event: dict[str, Any] = {
            "session_id": session_id,
            "request_id": request.request_id,
            "source": request.source,
            "payload": request.payload.model_dump(mode="json"),
            "timestamp": timestamp,
        }
        if request.tool_call_id is not None:
            event["tool_call_id"] = request.tool_call_id
        await websocket.send_json(
            {
                "event_type": "user.interaction.request",
                "session_id": session_id,
                "event": event,
                "timestamp": timestamp,
            }
        )


async def _forward_session_list_events(websocket: WebSocket) -> None:
    state = get_web_state_from_ws(websocket)
    if state.session_live is None:
        return
    subscription = state.session_live.stream.subscribe()
    try:
        async for event in subscription:
            await websocket.send_json(
                {
                    "type": event.type,
                    "session_id": event.session_id,
                    "session": event.session,
                }
            )
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
            "compact",
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

        await _send_pending_interaction_snapshots(session_id, websocket)
        send_task = asyncio.create_task(_forward_events(session_id, websocket))
        recv_task = asyncio.create_task(_receive_commands(session_id, websocket, is_holder=is_holder))
        done, pending = await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
        log_debug(
            f"[web/ws:{session_id[:8]}] first task completed done={len(done)} pending={len(pending)}",
            debug_type=DebugType.EXECUTION,
        )

        if pending:
            for task in pending:
                task.cancel()
            try:
                _ = await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=2.0)
                log_debug(
                    f"[web/ws:{session_id[:8]}] pending peer task cleanup finished",
                    debug_type=DebugType.EXECUTION,
                )
            except TimeoutError:
                log_debug(
                    f"[web/ws:{session_id[:8]}] pending peer task cleanup timed out",
                    debug_type=DebugType.EXECUTION,
                )

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
        log_debug(f"[web/ws:{session_id[:8]}] finally start", debug_type=DebugType.EXECUTION)
        with contextlib.suppress(Exception):
            log_debug(f"[web/ws:{session_id[:8]}] closing websocket", debug_type=DebugType.EXECUTION)
            await websocket.close()
            log_debug(f"[web/ws:{session_id[:8]}] websocket closed", debug_type=DebugType.EXECUTION)

        # Release holder on disconnect (starts grace period).
        if is_holder and holder_key is not None:
            state = get_web_state_from_ws(websocket)
            with contextlib.suppress(Exception):
                log_debug(f"[web/ws:{session_id[:8]}] releasing holder", debug_type=DebugType.EXECUTION)
                await state.runtime.release_holder(session_id, holder_key)
                log_debug(f"[web/ws:{session_id[:8]}] holder released", debug_type=DebugType.EXECUTION)

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
            try:
                _ = await asyncio.wait_for(asyncio.gather(*tasks_to_cancel, return_exceptions=True), timeout=2.0)
                log_debug(
                    f"[web/ws:{session_id[:8]}] final task cleanup finished count={len(tasks_to_cancel)}",
                    debug_type=DebugType.EXECUTION,
                )
            except TimeoutError:
                log_debug(
                    f"[web/ws:{session_id[:8]}] final task cleanup timed out count={len(tasks_to_cancel)}",
                    debug_type=DebugType.EXECUTION,
                )
        log_debug(f"[web/ws:{session_id[:8]}] finally done", debug_type=DebugType.EXECUTION)


async def _wait_for_ws_disconnect(websocket: WebSocket) -> None:
    """Block until the client disconnects or sends any message (ignored)."""
    try:
        while True:
            await websocket.receive()
    except (WebSocketDisconnect, anyio.ClosedResourceError, asyncio.CancelledError, FutureCancelledError):
        return


@router.websocket("/api/sessions/ws")
async def session_list_websocket(websocket: WebSocket) -> None:
    try:
        await websocket.accept()
        forward_task = asyncio.create_task(_forward_session_list_events(websocket))
        disconnect_task = asyncio.create_task(_wait_for_ws_disconnect(websocket))
        try:
            _done, _pending = await asyncio.wait({forward_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in (forward_task, disconnect_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(forward_task, disconnect_task, return_exceptions=True)
    except (WebSocketDisconnect, asyncio.CancelledError, FutureCancelledError):
        return
    finally:
        with contextlib.suppress(Exception):
            await websocket.close()
