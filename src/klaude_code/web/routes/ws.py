from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path
from typing import Any, Literal, cast

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from klaude_code.protocol import llm_param, message, model, op, user_interaction
from klaude_code.protocol.message import ImageFilePart, ImageURLPart, UserInputPayload
from klaude_code.session.session import Session
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


class ThinkingFrame(BaseModel):
    type: Literal["thinking"]
    thinking: llm_param.Thinking


type IncomingFrame = MessageFrame | InterruptFrame | RespondFrame | ContinueFrame | ModelFrame | ThinkingFrame


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
) -> None:
    state = get_web_state_from_ws(websocket)
    runtime = state.runtime

    try:
        if isinstance(frame, MessageFrame):
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

        await runtime.submit(
            op.ChangeThinkingOperation(
                session_id=session_id,
                thinking=frame.thinking,
            )
        )
        return
    except Exception as exc:
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
    return ThinkingFrame.model_validate(payload)


async def _forward_events(session_id: str, websocket: WebSocket) -> None:
    state = get_web_state_from_ws(websocket)
    subscription = state.event_bus.subscribe(session_id)
    try:
        async for envelope in subscription:
            await websocket.send_json(
                envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True)
            )
    except (WebSocketDisconnect, RuntimeError, anyio.ClosedResourceError):
        return


async def _receive_commands(session_id: str, websocket: WebSocket) -> None:
    while True:
        try:
            payload = await websocket.receive_json()
        except (WebSocketDisconnect, anyio.ClosedResourceError):
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
        if frame_type not in {"message", "interrupt", "respond", "continue", "model", "thinking"}:
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

        await _handle_incoming_frame(session_id, frame, websocket)


@router.websocket("/api/sessions/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    try:
        await websocket.accept()
        state = get_web_state_from_ws(websocket)
        work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if work_dir is None:
            await _send_error_frame(websocket, code="session_not_found", message=f"Session not found: {session_id}")
            await websocket.close(code=4004)
            return

        if not state.runtime.session_registry.has_session_actor(session_id):
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

        await websocket.send_json(_load_usage_snapshot(session_id, work_dir, websocket))

        send_task = asyncio.create_task(_forward_events(session_id, websocket))
        recv_task = asyncio.create_task(_receive_commands(session_id, websocket))
        done, pending = await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()
        if pending:
            _ = await asyncio.gather(*pending, return_exceptions=True)

        for task in done:
            with contextlib.suppress(asyncio.CancelledError):
                exc = task.exception()
                if exc is None:
                    continue
                if isinstance(exc, WebSocketDisconnect):
                    continue
                raise exc
    except (WebSocketDisconnect, asyncio.CancelledError):
        return
