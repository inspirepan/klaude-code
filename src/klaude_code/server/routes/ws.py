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

from klaude_code.agent.compaction import should_compact_threshold
from klaude_code.control.event_bus import EventSubscription
from klaude_code.control.user_interaction import PendingUserInteractionRequest
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, message, op
from klaude_code.protocol.models import TaskMetadataItem, Usage
from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.server.session_index import resolve_session_work_dir
from klaude_code.server.session_state import derive_session_state_from_snapshot
from klaude_code.server.state import ServerAppState, get_server_state_from_ws
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path

router = APIRouter(tags=["websocket"])

# Live connections per session. Used to decide when an abandoned empty
# session can be cleaned up on disconnect.
_ATTACH_COUNTS: dict[str, int] = {}


class OpFrame(BaseModel):
    """Submit any serialized protocol operation bound to the attached session."""

    type: Literal["op"]
    operation: dict[str, Any]


class EmitFrame(BaseModel):
    """Emit a shared narrative event (user message echo) onto the session bus."""

    type: Literal["emit"]
    event_type: str
    event: dict[str, Any]


class DequeueFollowUpsFrame(BaseModel):
    """Pop all queued follow-up messages (Esc-recall editing in the TUI)."""

    type: Literal["dequeue_follow_ups"]


type IncomingFrame = OpFrame | EmitFrame | DequeueFollowUpsFrame


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


def _extract_usage_from_history(history: list[message.HistoryEvent]) -> Usage | None:
    for item in reversed(history):
        if isinstance(item, TaskMetadataItem) and item.main_agent.usage is not None:
            return item.main_agent.usage
        if isinstance(item, message.AssistantMessage) and item.usage is not None:
            return item.usage
    return None


def _load_usage_snapshot(session_id: str, session_work_dir: Path, websocket: WebSocket) -> dict[str, Any]:
    usage = Usage()
    state = get_server_state_from_ws(websocket)

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


_WS_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _spawn_ws_task(coro: Any) -> None:
    task = asyncio.ensure_future(coro)
    _WS_BACKGROUND_TASKS.add(task)
    task.add_done_callback(_WS_BACKGROUND_TASKS.discard)


async def _emit_follow_up_queue_event(state: ServerAppState, session_id: str) -> None:
    actor = state.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    if agent is None:
        return
    await state.runtime.emit_event(
        events.FollowUpQueueUpdatedEvent(
            session_id=session_id,
            texts=[item.text for item in agent.follow_up_snapshot()],
        )
    )


async def _submit_user_turn(state: ServerAppState, run_op: op.RunAgentOperation) -> None:
    """Start a user turn: compact first when over threshold, queue when busy.

    Mirrors the old in-process TUI runner: threshold compaction runs before
    the turn, and a turn that raced an already-running task becomes a queued
    follow-up instead of a busy rejection.
    """
    runtime = state.runtime
    session_id = run_op.session_id

    def _agent_and_busy() -> tuple[Any, bool]:
        actor = runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        busy = actor is not None and not actor.snapshot().is_idle
        return agent, busy

    agent, busy = _agent_and_busy()
    if not busy and agent is not None:
        try:
            needs_compact = should_compact_threshold(
                session=agent.session,
                config=None,
                llm_config=agent.profile.llm_client.get_llm_config(),
            )
        except Exception:
            needs_compact = False
        if needs_compact:
            compact = op.CompactSessionOperation(session_id=session_id, reason="threshold", will_retry=False)
            await runtime.submit(compact)
            await runtime.wait_for(compact.id)
            _agent2, busy = _agent_and_busy()
    if busy:
        await runtime.submit(op.FollowUpAgentOperation(session_id=session_id, input=run_op.input))
        await _emit_follow_up_queue_event(state, session_id)
        return
    if state.headless is not None:
        # Guard the submit-to-task-start window against the follow-up drain.
        state.headless.mark_turn_starting(session_id, run_op.id)
    try:
        await runtime.submit(run_op)
    except BaseException:
        if state.headless is not None:
            state.headless.clear_turn_starting(session_id, run_op.id)
        raise


async def _handle_operation_frame(
    session_id: str,
    frame: OpFrame,
    websocket: WebSocket,
) -> None:
    state = get_server_state_from_ws(websocket)
    runtime = state.runtime
    try:
        operation = op.parse_operation(frame.operation)
    except Exception as exc:
        await _send_error_frame(websocket, code="invalid_operation", message=f"Failed to parse operation: {exc}")
        return
    bound_session = getattr(operation, "session_id", None)
    if bound_session != session_id:
        await _send_error_frame(
            websocket,
            code="operation_session_mismatch",
            message="Operation must target the attached session",
        )
        return
    try:
        if isinstance(operation, op.RunAgentOperation):
            # May wait on a threshold compaction; must not block the receive
            # loop (an interrupt frame could be right behind it).
            _spawn_ws_task(_submit_user_turn(state, operation))
            return
        if isinstance(operation, op.InterruptOperation):
            _spawn_ws_task(runtime.submit(operation))
            return
        await runtime.submit(operation)
        if isinstance(operation, op.FollowUpAgentOperation):
            # Submit is accepted before execution; the queue event needs the
            # applied state, so wait for the (cheap) operation to finish.
            await runtime.wait_for(operation.id)
            await _emit_follow_up_queue_event(state, session_id)
    except FutureCancelledError:
        return
    except Exception as exc:
        await _send_error_frame(websocket, code="invalid_payload", message=f"Failed to submit operation: {exc}")


async def _handle_incoming_frame(
    session_id: str,
    frame: IncomingFrame,
    websocket: WebSocket,
    *,
    can_input: bool,
) -> None:
    state = get_server_state_from_ws(websocket)
    runtime = state.runtime
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        await _send_error_frame(websocket, code="session_not_found", message=f"Session not found: {session_id}")
        return

    if not can_input:
        await _send_error_frame(
            websocket,
            code="peek_read_only",
            message="Peek connections cannot send commands",
        )
        return

    try:
        if isinstance(frame, OpFrame):
            await _handle_operation_frame(session_id, frame, websocket)
            return

        if isinstance(frame, EmitFrame):
            if frame.event_type != "user.message":
                await _send_error_frame(
                    websocket,
                    code="invalid_payload",
                    message=f"Event type not allowed for emit: {frame.event_type}",
                )
                return
            event = events.UserMessageEvent.model_validate({**frame.event, "session_id": session_id})
            await runtime.emit_event(event)
            return

        actor = runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        texts: list[str] = []
        if agent is not None:
            texts = [item.text for item in agent.pop_all_follow_up()]
            await _emit_follow_up_queue_event(state, session_id)
        await websocket.send_json({"type": "follow_ups_dequeued", "session_id": session_id, "texts": texts})
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
    if frame_type == "op":
        return OpFrame.model_validate(payload)
    if frame_type == "emit":
        return EmitFrame.model_validate(payload)
    return DequeueFollowUpsFrame.model_validate(payload)


def _collect_descendant_session_ids(session_id: str, work_dir: Path) -> set[str]:
    """Collect all descendant sub-agent session IDs by scanning session histories.

    Uses BFS to find SpawnSubAgentEntry items in the parent session and recurse
    into child sessions.  This is needed when there is no in-memory session
    snapshot (e.g. reattaching after a server restart) so that sub-agent
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

# Events that change what the prompt bar shows; the attach client gets a fresh
# session_info frame after each one.
_SESSION_INFO_REFRESH_EVENTS = (
    events.ModelChangedEvent,
    events.ThinkingChangedEvent,
    events.WelcomeEvent,
)


def _build_session_info(state: ServerAppState, session_id: str) -> dict[str, Any]:
    actor = state.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    snapshot = state.runtime.session_registry.snapshot(session_id)
    info: dict[str, Any] = {
        "type": "session_info",
        "session_id": session_id,
        "state": derive_session_state_from_snapshot(snapshot) if snapshot is not None else "idle",
        "model_config_name": None,
        "provider_name": None,
        "effort": None,
        "follow_ups": [],
        "work_dir": None,
        "title": None,
    }
    if agent is not None:
        info["model_config_name"] = agent.session.model_config_name
        info["follow_ups"] = [item.text for item in agent.follow_up_snapshot()]
        info["work_dir"] = str(agent.session.work_dir)
        info["title"] = agent.session.title
        try:
            llm_config = agent.profile.llm_client.get_llm_config()
            info["provider_name"] = llm_config.provider_name
            info["effort"] = llm_config.effective_effort
        except Exception:
            pass
    return info


def _synthetic_envelope_dict(event: events.Event) -> dict[str, Any]:
    """Wrap a locally synthesized event in a wire-parseable envelope (seq 0)."""
    envelope = events.EventEnvelope(
        event_id=uuid4().hex,
        event_seq=0,
        session_id=event.session_id,
        event_type=events.event_type_name(event),
        durability="ephemeral",
        timestamp=event.timestamp,
        event=event,
    )
    return envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True)


async def _send_attach_replay(session_id: str, websocket: WebSocket, *, state: ServerAppState) -> int:
    """Send welcome + spliced history/tape to this socket; return the max
    tape event_seq so the live stream can be deduplicated seamlessly.

    Must be called after the live subscription exists: any event published
    after the tape cut reaches the subscription with a higher seq, and any
    event recorded before it is on the tape — no gaps, no duplicates.
    """
    cut = state.tapes.cut(session_id) if state.tapes is not None else None
    base_len = cut.base_history_len if cut is not None else None

    actor = state.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    if agent is not None:
        session = agent.session
        welcome = events.WelcomeEvent(
            session_id=session_id,
            work_dir=str(session.work_dir),
            llm_config=agent.profile.llm_client.get_llm_config(),
            title=session.title,
        )
        await websocket.send_json(_synthetic_envelope_dict(welcome))
        # History events travel with explicit type tags: the replay union is
        # not a discriminated union, so bare dicts cannot be re-parsed safely.
        history_events = list(session.get_history_item(limit=base_len))
        chunk_size = 2000
        for start in range(0, len(history_events), chunk_size) or [0]:
            chunk = history_events[start : start + chunk_size]
            await websocket.send_json(
                {
                    "type": "replay_history",
                    "session_id": session_id,
                    "updated_at": session.updated_at,
                    "events": [
                        {
                            "event_type": events.event_type_name(item),
                            "event": item.model_dump(mode="json", exclude_none=True, serialize_as_any=True),
                        }
                        for item in chunk
                    ],
                }
            )
    if cut is not None and cut.envelopes:
        batch: list[dict[str, Any]] = []
        for envelope in cut.envelopes:
            batch.append(envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True))
            if len(batch) >= 200:
                await websocket.send_json(batch)
                batch = []
        if batch:
            await websocket.send_json(batch)
    await websocket.send_json({"type": "replay_complete", "session_id": session_id})
    return cut.max_event_seq if cut is not None else 0


async def _forward_events(
    session_id: str,
    websocket: WebSocket,
    *,
    subscription: EventSubscription | None = None,
    skip_seq_at_or_below: int = 0,
    send_session_info_updates: bool = False,
) -> None:
    state = get_server_state_from_ws(websocket)
    if subscription is None:
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
                    f"[ws:{session_id[:8]}] tracked {len(tracked_child_session_ids)} descendant session(s) from history",
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

                # Attach replay dedup: events already delivered via the tape
                # snapshot arrive here with a seq at or below the cut.
                if (
                    skip_seq_at_or_below > 0
                    and envelope.session_id == session_id
                    and 0 < envelope.event_seq <= skip_seq_at_or_below
                ):
                    continue

                serialized = envelope.model_dump(mode="json", exclude_none=True, serialize_as_any=True)
                await send_queue.put(serialized)
                if (
                    send_session_info_updates
                    and envelope.session_id == session_id
                    and isinstance(envelope.event, _SESSION_INFO_REFRESH_EVENTS)
                ):
                    await send_queue.put(_build_session_info(state, session_id))
        except (
            WebSocketDisconnect,
            RuntimeError,
            anyio.ClosedResourceError,
            asyncio.CancelledError,
            FutureCancelledError,
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
            WebSocketDisconnect,
            RuntimeError,
            anyio.ClosedResourceError,
            asyncio.CancelledError,
            FutureCancelledError,
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
    state = get_server_state_from_ws(websocket)
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
        # Full envelope shape so clients parse it like a live event.
        request_event = events.UserInteractionRequestEvent(
            session_id=session_id,
            request_id=request.request_id,
            source=request.source,
            payload=request.payload,
            tool_call_id=request.tool_call_id,
        )
        await websocket.send_json(_synthetic_envelope_dict(request_event))


async def _receive_commands(
    session_id: str,
    websocket: WebSocket,
    *,
    can_input: bool = False,
) -> None:
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
        payload = cast(dict[str, Any], payload)

        frame_type = payload.get("type")
        if not isinstance(frame_type, str):
            await _send_error_frame(websocket, code="invalid_message", message="Missing message type")
            continue
        if frame_type not in {"op", "emit", "dequeue_follow_ups"}:
            await _send_error_frame(websocket, code="unknown_type", message=f"Unknown message type: {frame_type}")
            continue

        try:
            frame = _validate_incoming_frame(payload, frame_type)
        except ValidationError as exc:
            await _send_error_frame(
                websocket,
                code="invalid_payload",
                message="Invalid payload",
                detail=exc.errors(),
            )
            continue

        await _handle_incoming_frame(session_id, frame, websocket, can_input=can_input)


@router.websocket("/api/sessions/{session_id}/ws")
async def session_websocket(websocket: WebSocket, session_id: str) -> None:
    send_task: asyncio.Task[None] | None = None
    recv_task: asyncio.Task[None] | None = None
    attach_mode = False
    counted = False
    try:
        await websocket.accept()
        state = get_server_state_from_ws(websocket)
        attach_mode = websocket.query_params.get("replay") == "1"
        peek_mode = websocket.query_params.get("peek") == "1"
        work_dir = resolve_session_work_dir(state.home_dir, session_id)
        if work_dir is None:
            await _send_error_frame(websocket, code="session_not_found", message=f"Session not found: {session_id}")
            await websocket.close(code=4004)
            return

        if not state.runtime.session_registry.has_session_actor(session_id):
            try:
                await state.runtime.submit_and_wait(
                    op.InitAgentOperation(
                        session_id=session_id,
                        work_dir=work_dir,
                        # Attach replays per-connection; never broadcast the
                        # rehydration replay to every other client on the bus.
                        defer_welcome_context=attach_mode,
                        defer_replay=attach_mode,
                    )
                )
            except Exception as exc:
                await _send_error_frame(
                    websocket,
                    code="session_init_failed",
                    message=f"Failed to initialize session: {exc}",
                )
                await websocket.close(code=4005)
                return

        # Every connected client may type (peek is explicitly read-only);
        # the session actor serializes execution (§4.9).
        can_input = not peek_mode
        _ATTACH_COUNTS[session_id] = _ATTACH_COUNTS.get(session_id, 0) + 1
        counted = True
        await websocket.send_json(
            {
                "type": "connection_info",
                "can_input": can_input,
                "session_id": session_id,
                "protocol_version": PROTOCOL_VERSION,
                "code_fingerprint": state.code_fingerprint,
            }
        )
        if attach_mode:
            await websocket.send_json(_build_session_info(state, session_id))
            await websocket.send_json(_load_usage_snapshot(session_id, work_dir, websocket))
            # Subscribe, then cut the tape inside the same event-loop step
            # (no await between): everything after the cut reaches the
            # subscription, everything before it is on the tape.
            subscription = state.subscribe_events(None)
            max_seq = await _send_attach_replay(session_id, websocket, state=state)
            await _send_pending_interaction_snapshots(session_id, websocket)
            send_task = asyncio.create_task(
                _forward_events(
                    session_id,
                    websocket,
                    subscription=subscription,
                    skip_seq_at_or_below=max_seq,
                    send_session_info_updates=True,
                )
            )
        else:
            await websocket.send_json(_load_usage_snapshot(session_id, work_dir, websocket))
            await _send_pending_interaction_snapshots(session_id, websocket)
            send_task = asyncio.create_task(_forward_events(session_id, websocket))
        recv_task = asyncio.create_task(_receive_commands(session_id, websocket, can_input=can_input))
        done, pending = await asyncio.wait({send_task, recv_task}, return_when=asyncio.FIRST_COMPLETED)
        log_debug(
            f"[ws:{session_id[:8]}] first task completed done={len(done)} pending={len(pending)}",
            debug_type=DebugType.EXECUTION,
        )

        if pending:
            for task in pending:
                task.cancel()
            try:
                _ = await asyncio.wait_for(asyncio.gather(*pending, return_exceptions=True), timeout=2.0)
                log_debug(
                    f"[ws:{session_id[:8]}] pending peer task cleanup finished",
                    debug_type=DebugType.EXECUTION,
                )
            except TimeoutError:
                log_debug(
                    f"[ws:{session_id[:8]}] pending peer task cleanup timed out",
                    debug_type=DebugType.EXECUTION,
                )

        for task in done:
            with contextlib.suppress(asyncio.CancelledError, FutureCancelledError):
                exc = task.exception()
                if exc is not None and not isinstance(exc, WebSocketDisconnect):
                    raise exc
    except (WebSocketDisconnect, asyncio.CancelledError, FutureCancelledError):
        return
    finally:
        log_debug(f"[ws:{session_id[:8]}] finally start", debug_type=DebugType.EXECUTION)
        with contextlib.suppress(Exception):
            log_debug(f"[ws:{session_id[:8]}] closing websocket", debug_type=DebugType.EXECUTION)
            await websocket.close()
            log_debug(f"[ws:{session_id[:8]}] websocket closed", debug_type=DebugType.EXECUTION)

        # Drop an abandoned empty session once the last connected client
        # detaches. Running sessions are never touched — detach must keep
        # the agent alive.
        if counted:
            state = get_server_state_from_ws(websocket)
            remaining = _ATTACH_COUNTS.get(session_id, 1) - 1
            if remaining <= 0:
                _ATTACH_COUNTS.pop(session_id, None)
            else:
                _ATTACH_COUNTS[session_id] = remaining
            if remaining <= 0:
                with contextlib.suppress(Exception):
                    registry = cast(Any, state.runtime.session_registry)
                    actor = registry.get_session_actor(session_id)
                    agent = actor.get_agent() if actor is not None else None
                    if agent is not None and agent.session.messages_count == 0 and actor.snapshot().is_idle:
                        closed = await state.runtime.close_session(session_id)
                        if closed:
                            if state.tapes is not None:
                                state.tapes.drop(session_id)
                            shutil.rmtree(
                                Session.paths(agent.session.work_dir).session_dir(session_id),
                                ignore_errors=True,
                            )

        tasks_to_cancel = [task for task in (send_task, recv_task) if task is not None and not task.done()]
        for task in tasks_to_cancel:
            task.cancel()
        if tasks_to_cancel:
            try:
                _ = await asyncio.wait_for(asyncio.gather(*tasks_to_cancel, return_exceptions=True), timeout=2.0)
                log_debug(
                    f"[ws:{session_id[:8]}] final task cleanup finished count={len(tasks_to_cancel)}",
                    debug_type=DebugType.EXECUTION,
                )
            except TimeoutError:
                log_debug(
                    f"[ws:{session_id[:8]}] final task cleanup timed out count={len(tasks_to_cancel)}",
                    debug_type=DebugType.EXECUTION,
                )
        log_debug(f"[ws:{session_id[:8]}] finally done", debug_type=DebugType.EXECUTION)
