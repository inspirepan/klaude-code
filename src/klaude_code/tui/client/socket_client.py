"""UDS WebSocket implementation of ``RuntimeClient``.

Connects to the local klaude server socket, performs the attach handshake
(replay splice included), mirrors session state for the prompt bar, and
routes envelopes to the display through a serialized queue.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from collections import deque
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events, op
from klaude_code.protocol.events import EventEnvelope, parse_event_envelope
from klaude_code.protocol.version import PROTOCOL_VERSION, is_protocol_compatible
from klaude_code.server.paths import server_socket_path
from klaude_code.tui.client.base import ClientConnectionError, SessionInfoSnapshot

# Sentinel type for the display queue.
_DisplayItem = EventEnvelope

# A pending echo swallow older than this is stale: its canonical echo was
# lost (send failed mid-flight, server dropped the emit). Expire it so it
# cannot eat a later user message that happens to repeat the same text.
_ECHO_SWALLOW_TTL_SECONDS = 60.0


def _local_envelope(event: events.Event) -> EventEnvelope:
    """Wrap a client-local event (toggle, refresh, welcome context) for display."""
    from uuid import uuid4

    return EventEnvelope(
        event_id=uuid4().hex,
        event_seq=0,
        session_id=event.session_id,
        event_type=events.event_type_name(event),
        durability="ephemeral",
        timestamp=event.timestamp,
        event=event,
    )


class SocketRuntimeClient:
    """RuntimeClient over the server's Unix socket (WS frame protocol)."""

    def __init__(
        self,
        session_id: str,
        *,
        on_envelope: Callable[[EventEnvelope], Awaitable[None]],
        on_session_info: Callable[[SessionInfoSnapshot], None] | None = None,
        peek: bool = False,
        welcome_context_provider: Callable[[], Awaitable[events.WelcomeContextEvent | None]] | None = None,
    ) -> None:
        self._session_id = session_id
        self._on_envelope = on_envelope
        self._on_session_info = on_session_info
        self._peek = peek
        self._welcome_context_provider = welcome_context_provider
        self._welcome_context_pending = False

        self._ws: Any = None
        self._recv_task: asyncio.Task[None] | None = None
        self._display_task: asyncio.Task[None] | None = None
        self._display_queue: asyncio.Queue[_DisplayItem] = asyncio.Queue()
        self._display_started = False

        self._op_futures: dict[str, asyncio.Future[None]] = {}
        self._completed_ops: set[str] = set()
        self._my_op_ids: set[str] = set()

        self._info = SessionInfoSnapshot(session_id=session_id)
        self._running = False
        self._state_changed = asyncio.Event()
        self._replay_complete = asyncio.Event()
        self._connection_lost = asyncio.Event()
        self._interrupt_prefill: str | None = None
        self._interaction_queue: asyncio.Queue[events.UserInteractionRequestEvent] = asyncio.Queue()
        self._dequeue_future: asyncio.Future[tuple[str, ...]] | None = None
        self._closed = False
        # (content, monotonic timestamp) of locally echoed user messages whose
        # canonical server echo must be dropped instead of rendered twice.
        self._pending_echo_swallows: deque[tuple[str, float]] = deque()

    # -- lifecycle --

    @property
    def session_id(self) -> str:
        return self._session_id

    def can_input(self) -> bool:
        return not self._peek

    async def start(self) -> None:
        await self._connect()

    async def _connect(self) -> None:
        from websockets.asyncio.client import unix_connect

        socket_path = server_socket_path()
        uri = f"ws://klaude/api/sessions/{self._session_id}/ws?replay=1"
        if self._peek:
            uri += "&peek=1"
        self._ws = await unix_connect(
            path=str(socket_path),
            uri=uri,
            max_size=64 * 1024 * 1024,
            ping_interval=None,
        )
        self._replay_complete = asyncio.Event()
        self._welcome_context_pending = self._welcome_context_provider is not None
        self._closed = False
        self._connection_lost.clear()
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def close(self) -> None:
        self._closed = True
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        if self._display_task is not None and not self._display_task.done():
            # Let queued display work drain before stopping.
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._display_queue.join(), timeout=2.0)
            self._display_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._display_task
        for future in self._op_futures.values():
            if not future.done():
                future.set_result(None)
        self._op_futures.clear()

    async def reattach(self, session_id: str) -> None:
        # A deliberate reconnect: keep the recv loop's cancellation from
        # taking the connection-lost path (spurious error + auto-detach).
        self._closed = True
        if self._recv_task is not None and not self._recv_task.done():
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
        self._session_id = session_id
        self._info = SessionInfoSnapshot(session_id=session_id)
        self._running = False
        self._interrupt_prefill = None
        # Stale swallows must not eat user messages replayed by the new attach.
        self._pending_echo_swallows.clear()
        self._notify_state_changed()
        await self._connect()

    # -- display feed --

    def start_display(self) -> None:
        if self._display_started:
            return
        self._display_started = True
        self._display_task = asyncio.create_task(self._display_loop())

    async def _display_loop(self) -> None:
        while True:
            envelope = await self._display_queue.get()
            try:
                await self._on_envelope(envelope)
            except Exception as exc:
                log_debug(f"[client] display consumer failed: {exc}", debug_type=DebugType.EXECUTION)
            finally:
                self._display_queue.task_done()

    async def wait_for_display_idle(self) -> None:
        if not self._display_started:
            return
        await self._display_queue.join()

    async def wait_for_replay_complete(self) -> None:
        await self._replay_complete.wait()

    # -- send helpers --

    async def _send(self, frame: dict[str, Any]) -> None:
        if self._ws is None:
            raise ClientConnectionError("client is not connected")
        try:
            await self._ws.send(json.dumps(frame))
        except (TypeError, ValueError):
            raise
        except Exception as exc:
            raise ClientConnectionError(f"connection to klaude server lost: {exc}") from exc

    async def submit(self, operation: op.Operation) -> str:
        payload = operation.model_dump(mode="json", exclude_none=True)
        self._my_op_ids.add(operation.id)
        if operation.id not in self._completed_ops and operation.id not in self._op_futures:
            self._op_futures[operation.id] = asyncio.get_running_loop().create_future()
        await self._send({"type": "op", "operation": payload})
        return operation.id

    async def wait_for(self, operation_id: str) -> None:
        if operation_id in self._completed_ops:
            self._completed_ops.discard(operation_id)
            return
        future = self._op_futures.get(operation_id)
        if future is None:
            return
        try:
            await future
        finally:
            self._op_futures.pop(operation_id, None)
            self._completed_ops.discard(operation_id)

    async def submit_and_wait(self, operation: op.Operation) -> None:
        await self.submit(operation)
        await self.wait_for(operation.id)

    async def emit_user_message(self, event: events.UserMessageEvent) -> None:
        # Optimistic local echo: render right away instead of waiting for the
        # server round trip (a busy server loop can hold the canonical echo
        # for seconds on the first turn). The emit still goes to the server —
        # the session tape and other attached clients need it — and
        # _handle_envelope swallows the matching echo when it comes back.
        await self._display_queue.put(_local_envelope(event))
        await self._send(
            {
                "type": "emit",
                "event_type": "user.message",
                "event": event.model_dump(mode="json", exclude_none=True),
            }
        )
        # Arm the swallow only after the emit reached the wire: a failed send
        # produces no canonical echo, and a stale entry would eat the next
        # user message that repeats the same text.
        self._pending_echo_swallows.append((event.content, time.monotonic()))

    async def emit_local_event(self, event: events.Event) -> None:
        await self._display_queue.put(_local_envelope(event))

    async def dequeue_follow_ups(self) -> tuple[str, ...]:
        # Optimistic local clear; the server pop confirms asynchronously.
        texts = self._info.follow_ups
        self._info.follow_ups = ()
        self._notify_state_changed()
        future: asyncio.Future[tuple[str, ...]] = asyncio.get_running_loop().create_future()
        self._dequeue_future = future
        await self._send({"type": "dequeue_follow_ups"})
        try:
            confirmed = await asyncio.wait_for(future, timeout=5.0)
            return confirmed
        except TimeoutError:
            return texts
        finally:
            self._dequeue_future = None

    # -- mirrors --

    def is_running(self) -> bool:
        return self._running

    def follow_up_texts(self) -> tuple[str, ...]:
        return self._info.follow_ups

    def optimistically_append_follow_ups(self, texts: Sequence[str]) -> None:
        self._info.follow_ups = (*self._info.follow_ups, *texts)
        self._notify_state_changed()

    def session_info(self) -> SessionInfoSnapshot:
        return self._info

    def consume_interrupt_prefill(self) -> str | None:
        text = self._interrupt_prefill
        self._interrupt_prefill = None
        return text

    def state_changed_event(self) -> asyncio.Event:
        return self._state_changed

    def connection_lost_event(self) -> asyncio.Event:
        return self._connection_lost

    def interaction_requests(self) -> asyncio.Queue[events.UserInteractionRequestEvent]:
        return self._interaction_queue

    def _notify_state_changed(self) -> None:
        self._state_changed.set()

    # -- receive path --

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    data = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    continue
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    await self._handle_frame(item)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_debug(f"[client] recv loop ended: {exc}", debug_type=DebugType.EXECUTION)
        finally:
            if not self._closed:
                # Server went away: surface it and unblock waiters.
                self._running = False
                self._replay_complete.set()
                self._connection_lost.set()
                self._notify_state_changed()
                for future in self._op_futures.values():
                    if not future.done():
                        future.set_result(None)
                with contextlib.suppress(Exception):
                    await self._display_queue.put(
                        _local_envelope(
                            events.ErrorEvent(
                                session_id=self._session_id,
                                error_message="Connection to klaude server lost. Reattach with: klaude attach "
                                + self._session_id[:8],
                                can_retry=False,
                            )
                        )
                    )

    async def _handle_frame(self, item: dict[str, Any]) -> None:
        if "event_type" in item:
            try:
                envelope = parse_event_envelope(item)
            except ValueError:
                # Unknown/synthetic event types (e.g. usage.snapshot) are
                # not part of the display contract for the TUI client.
                return
            await self._handle_envelope(envelope)
            return

        frame_type = item.get("type")
        if frame_type == "session_info":
            self._apply_session_info(item)
            return
        if frame_type == "replay_history":
            parsed: list[events.Event] = []
            for raw in item.get("events") or []:
                if not isinstance(raw, dict):
                    continue
                try:
                    parsed.append(events.parse_event(str(raw.get("event_type")), raw.get("event") or {}))
                except ValueError:
                    continue
            # Instances are already concrete event classes; validate through
            # the model so the replay union accepts them.
            replay_event = events.ReplayHistoryEvent.model_validate(
                {
                    "session_id": str(item.get("session_id") or self._session_id),
                    "events": parsed,
                    "updated_at": float(item.get("updated_at") or 0.0),
                }
            )
            await self._display_queue.put(_local_envelope(replay_event))
            return
        if frame_type == "replay_complete":
            self._replay_complete.set()
            return
        if frame_type == "follow_ups_dequeued":
            texts = tuple(str(t) for t in item.get("texts", []))
            if self._dequeue_future is not None and not self._dequeue_future.done():
                self._dequeue_future.set_result(texts)
            return
        if frame_type == "error":
            message = str(item.get("message", "server error"))
            code = str(item.get("code", ""))
            log_debug(f"[client] server error frame code={code}: {message}", debug_type=DebugType.EXECUTION)
            await self._display_queue.put(
                _local_envelope(events.ErrorEvent(session_id=self._session_id, error_message=message, can_retry=False))
            )
            return
        if frame_type == "connection_info":
            await self._check_server_code(item)
            return
        # Other frames need no client action.

    async def _check_server_code(self, item: dict[str, Any]) -> None:
        """Compatibility handshake: show an error notice for any mismatch."""
        from klaude_code.update import get_code_fingerprint

        server_protocol = item.get("protocol_version")
        server_fingerprint = item.get("code_fingerprint")
        if not isinstance(server_fingerprint, str):
            server_fingerprint = ""
        local_fingerprint = get_code_fingerprint()
        protocol_matches = is_protocol_compatible(server_protocol)
        fingerprint_matches = server_fingerprint == local_fingerprint
        if protocol_matches and fingerprint_matches:
            return
        if not protocol_matches:
            detail = f"protocol server={server_protocol!r}, client={PROTOCOL_VERSION}"
        else:
            detail = f"code server={server_fingerprint or 'unknown'}, client={local_fingerprint}"
        await self._display_queue.put(
            _local_envelope(
                events.NoticeEvent(
                    session_id=self._session_id,
                    content=(
                        f"Server/client compatibility mismatch ({detail}). "
                        "Restart the server with: klaude server reload --force"
                    ),
                    is_error=True,
                )
            )
        )

    def _apply_session_info(self, item: dict[str, Any]) -> None:
        info = self._info
        info.session_id = str(item.get("session_id") or self._session_id)
        info.state = str(item.get("state") or "idle")
        info.model_config_name = item.get("model_config_name")
        info.provider_name = item.get("provider_name")
        info.effort = item.get("effort")
        info.work_dir = item.get("work_dir")
        info.title = item.get("title")
        info.follow_ups = tuple(str(t) for t in item.get("follow_ups") or [])
        # waiting_user_input is busy too: typing then must queue as a
        # follow-up. Treating it as idle started a duplicate turn — the local
        # echo plus the drain's replay rendered the same message twice.
        self._running = info.state in ("running", "waiting_user_input")
        self._notify_state_changed()
        if self._on_session_info is not None:
            with contextlib.suppress(Exception):
                self._on_session_info(info)

    async def _handle_envelope(self, envelope: EventEnvelope) -> None:
        event = envelope.event
        if isinstance(event, events.OperationFinishedEvent | events.OperationRejectedEvent):
            operation_id = event.operation_id
            future = self._op_futures.pop(operation_id, None)
            if future is not None and not future.done():
                self._completed_ops.add(operation_id)
                future.set_result(None)
            elif operation_id in self._my_op_ids:
                self._completed_ops.add(operation_id)
        if envelope.session_id == self._session_id:
            if isinstance(event, events.TaskStartEvent):
                self._running = True
                self._notify_state_changed()
            elif isinstance(event, events.TaskFinishEvent | events.InterruptEvent):
                self._running = False
                self._notify_state_changed()
            elif isinstance(event, events.FollowUpQueueUpdatedEvent):
                self._info.follow_ups = tuple(event.texts)
                self._notify_state_changed()
            elif isinstance(event, events.UserMessageRetractedEvent):
                if envelope.operation_id is not None and envelope.operation_id in self._my_op_ids:
                    self._interrupt_prefill = event.content
            elif isinstance(event, events.UserInteractionRequestEvent):
                self._interaction_queue.put_nowait(event)
            if isinstance(event, events.UserMessageEvent) and self._swallow_pending_echo(event.content):
                # Canonical echo of a message this client already rendered.
                return
        if (
            self._welcome_context_pending
            and isinstance(event, events.WelcomeEvent)
            and envelope.session_id == self._session_id
            and not self._replay_complete.is_set()
        ):
            # Attach-handshake welcome: chase it with the locally built
            # context (skills, memories) so the block lands ahead of the
            # history replay instead of trailing the whole transcript.
            self._welcome_context_pending = False
            await self._display_queue.put(envelope)
            assert self._welcome_context_provider is not None
            try:
                context_event = await self._welcome_context_provider()
            except Exception as exc:
                log_debug(f"[client] welcome context failed: {exc}", debug_type=DebugType.EXECUTION)
                return
            if context_event is not None:
                await self._display_queue.put(_local_envelope(context_event))
            return

        await self._display_queue.put(envelope)

    def _swallow_pending_echo(self, content: str) -> bool:
        now = time.monotonic()
        while self._pending_echo_swallows and now - self._pending_echo_swallows[0][1] > _ECHO_SWALLOW_TTL_SECONDS:
            self._pending_echo_swallows.popleft()
        if self._pending_echo_swallows and self._pending_echo_swallows[0][0] == content:
            self._pending_echo_swallows.popleft()
            return True
        return False
