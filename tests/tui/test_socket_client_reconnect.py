"""Client reattach behavior when the socket drops — usually a server reload.

A server reload re-execs the process in place, which cuts off every attached
client. The session itself is durable, so the client retries the attach inside
a bounded window instead of declaring the connection lost and detaching.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import socket
import tempfile
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import serve

from klaude_code import update
from klaude_code.protocol import events
from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.tui.client import socket_client
from klaude_code.tui.client.base import ClientConnectionError
from klaude_code.tui.client.socket_client import SocketRuntimeClient

_TEST_FINGERPRINT = "git:test"


async def _ignore_envelope(_envelope: events.EventEnvelope) -> None:
    return


def _fast_retry(monkeypatch: pytest.MonkeyPatch, *, grace: float, notice_delay: float = 60.0) -> None:
    monkeypatch.setattr(socket_client, "_RECONNECT_GRACE_SECONDS", grace)
    monkeypatch.setattr(socket_client, "_RECONNECT_INTERVAL_SECONDS", 0.01)
    monkeypatch.setattr(socket_client, "_RECONNECT_NOTICE_DELAY_SECONDS", notice_delay)


def _serve_handshake_on_unix_socket(path: Path, uris: list[str], connections: list[Any]) -> Any:
    """Start a throwaway WS server on `path` that mimics the attach handshake."""

    async def handler(websocket: Any) -> None:
        uris.append(str(getattr(getattr(websocket, "request", None), "path", "")))
        await websocket.send(
            json.dumps(
                {
                    "type": "connection_info",
                    "can_input": True,
                    "session_id": "session-id",
                    "protocol_version": PROTOCOL_VERSION,
                    "code_fingerprint": _TEST_FINGERPRINT,
                }
            )
        )
        await websocket.send(
            json.dumps(
                {
                    "type": "session_info",
                    "session_id": "session-id",
                    "state": "idle",
                    "follow_ups": [],
                }
            )
        )
        await websocket.send(json.dumps({"type": "replay_complete", "session_id": "session-id"}))
        connections.append(websocket)
        await websocket.wait_closed()

    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(path))
    listener.listen(8)
    listener.setblocking(False)
    return serve(handler, sock=listener)


def test_dropped_socket_reattaches_without_losing_the_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry(monkeypatch, grace=2.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    client._transcript_loaded = True
    attempts: list[bool] = []

    async def fake_connect(*, resume: bool = False) -> None:
        attempts.append(resume)
        if len(attempts) < 3:
            raise OSError("server socket is gone")
        # A real reattach settles the handshake from the server's frames.
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())

    assert attempts == [True, True, True]
    assert not client._connection_lost.is_set()
    assert client._reconnecting is False
    assert client._reconnect_task is None


def test_reattach_uses_full_handshake_without_a_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    """An initial attach that never completed its replay must not resume: it
    has no transcript to skip the history replay with."""
    _fast_retry(monkeypatch, grace=2.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    assert client._transcript_loaded is False
    attempts: list[bool] = []

    async def fake_connect(*, resume: bool = False) -> None:
        attempts.append(resume)
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())
    assert attempts == [False]


def test_reattach_gives_up_after_grace_and_reports_connection_lost(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry(monkeypatch, grace=0.2, notice_delay=0.05)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        raise OSError("server is gone for good")

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> list[events.Event]:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task
        surfaced: list[events.Event] = []
        while not client._display_queue.empty():
            surfaced.append(client._display_queue.get_nowait().event)
        return surfaced

    surfaced = asyncio.run(scenario())

    assert client._connection_lost.is_set()
    assert client._reconnecting is False
    assert any(isinstance(event, events.NoticeEvent) for event in surfaced)
    error = next(event for event in surfaced if isinstance(event, events.ErrorEvent))
    assert "Connection to klaude server lost" in error.error_message


def test_announced_outage_reports_its_recovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """An outage long enough to be announced must also report that it ended:
    otherwise the transcript is left on a "reattaching…" line forever."""
    _fast_retry(monkeypatch, grace=5.0, notice_delay=0.05)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    attempts = 0

    async def fake_connect(*, resume: bool = False) -> None:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            # Slow enough that the outage outlives the notice delay.
            await asyncio.sleep(0.05)
            raise OSError("server socket is gone")
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> list[events.Event]:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task
        return _surfaced_events(client)

    surfaced = asyncio.run(scenario())

    notices = [event.content for event in surfaced if isinstance(event, events.NoticeEvent)]
    assert notices == [
        "Connection to klaude server dropped; reattaching…",
        "Connection to klaude server restored.",
    ]
    assert client._reconnect_notice_shown is False


def test_quiet_reattach_leaves_the_transcript_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """A reattach inside the notice delay stays invisible: no drop line, and so
    no recovery line either."""
    _fast_retry(monkeypatch, grace=5.0, notice_delay=60.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())
    assert _surfaced_events(client) == []


def test_a_flap_after_a_recovery_announces_a_new_outage(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loop hands over to a fresh one when the socket it just recovered on
    dies immediately. The recovery line already closed the previous notice, so
    the new outage announces itself instead of leaving the transcript on an
    unresolved "reattaching…" line."""
    _fast_retry(monkeypatch, grace=5.0, notice_delay=0.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    attempts = 0

    async def fake_connect(*, resume: bool = False) -> None:
        nonlocal attempts
        attempts += 1
        client._handshake_ok = True
        client._handshake_settled.set()
        if attempts == 1:
            # The socket this loop just recovered on dies before it can return,
            # which is what makes the loop restore the reattach.
            client._reconnect_pending = True

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> list[events.Event]:
        client._schedule_reconnect()
        for _ in range(5):
            task = client._reconnect_task
            if task is None:
                break
            await task
        return _surfaced_events(client)

    surfaced = asyncio.run(scenario())

    notices = [event.content for event in surfaced if isinstance(event, events.NoticeEvent)]
    assert notices == [
        "Connection to klaude server dropped; reattaching…",
        "Connection to klaude server restored.",
        "Connection to klaude server dropped; reattaching…",
        "Connection to klaude server restored.",
    ]
    assert attempts == 2
    assert not client._connection_lost.is_set()


def test_send_waits_out_an_inflight_reattach() -> None:
    """A submit that lands during the restart window waits for the reattach
    instead of failing on the dead socket and detaching the TUI."""
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def scenario() -> None:
        client._reconnecting = True
        client._reconnect_done.clear()
        send_task = asyncio.create_task(client._send({"type": "op"}))
        await asyncio.sleep(0.05)
        assert not send_task.done()
        client._reconnecting = False
        client._reconnect_done.set()
        # No reattach happened here, so the send now reports the dead socket.
        with pytest.raises(ClientConnectionError):
            await send_task

    asyncio.run(scenario())


def test_socket_dropping_mid_handshake_does_not_extend_the_grace_window(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server that accepts and immediately drops must be retried, but must not
    reset the window — otherwise the client reconnects forever."""
    _fast_retry(monkeypatch, grace=0.3)
    monkeypatch.setattr(socket_client, "_RECONNECT_HANDSHAKE_TIMEOUT_SECONDS", 0.05)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    attempts = 0

    async def fake_connect(*, resume: bool = False) -> None:
        nonlocal attempts
        attempts += 1
        # Accepted, then dropped before the handshake completed.

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())

    assert attempts > 1, "a mid-handshake drop must be retried"
    assert client._connection_lost.is_set()


def test_refused_session_gives_up_without_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    _fast_retry(monkeypatch, grace=30.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        raise AssertionError("a refused session must not be retried")

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._settle_handshake(ok=False)
        await client._handle_frame({"type": "error", "code": "session_not_found", "message": "Session not found: x"})
        assert client._attach_fatal
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())
    assert client._connection_lost.is_set()


def test_handshake_then_drop_still_runs_out_of_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """A server that completes the handshake and then drops must not keep buying
    a new window: the client has to give up and report the loss."""
    _fast_retry(monkeypatch, grace=0.3)
    monkeypatch.setattr(socket_client, "_RECONNECT_STABLE_SECONDS", 60.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    attempts = 0

    async def fake_connect(*, resume: bool = False) -> None:
        nonlocal attempts
        attempts += 1
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        # Each iteration is one outage: the socket dies right after the handshake
        # the reconnect loop just completed.
        for _ in range(50):
            if client._connection_lost.is_set():
                return
            client._schedule_reconnect()
            task = client._reconnect_task
            if task is None:
                return
            await task
        raise AssertionError("grace window never ran out")

    asyncio.run(scenario())

    # The retries stay bounded by the budget and end in a reported loss rather
    # than a fresh window per flap.
    assert attempts > 0
    assert client._connection_lost.is_set()


def test_code_mismatch_during_reattach_allows_same_protocol(monkeypatch: pytest.MonkeyPatch) -> None:
    """An old TUI can resume after a source update restarts the server."""
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:mine")
    _fast_retry(monkeypatch, grace=30.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    attempts = 0

    async def fake_connect(*, resume: bool = False) -> None:
        nonlocal attempts
        attempts += 1
        await client._check_server_code({"protocol_version": PROTOCOL_VERSION, "code_fingerprint": "git:other"})
        assert not client._handshake_settled.is_set()
        await client._handle_frame({"type": "replay_complete", "session_id": "session-id"})

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())
    assert attempts == 1
    assert not client._attach_fatal
    assert not client._connection_lost.is_set()
    # The resume goes through, and the user learns the server moved on.
    notice = client._display_queue.get_nowait().event
    assert isinstance(notice, events.NoticeEvent)
    assert "Server restarted on updated code (git:other)" in notice.content
    assert not notice.is_error
    assert client._display_queue.empty()


def test_protocol_mismatch_during_reattach_refuses_to_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:mine")
    _fast_retry(monkeypatch, grace=30.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        await client._check_server_code({"protocol_version": PROTOCOL_VERSION + 1, "code_fingerprint": "git:other"})

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> None:
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task

    asyncio.run(scenario())
    assert client._attach_fatal
    assert client._connection_lost.is_set()


def test_initial_attach_mismatch_only_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    """An initial attach often lands on a server still awaiting its reload (the
    auto-reload is refused while a session is busy). That must not disable
    reattaching once it restarts onto matching code."""
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:mine")
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def scenario() -> None:
        assert not client._reconnecting
        await client._check_server_code({"protocol_version": PROTOCOL_VERSION, "code_fingerprint": "git:other"})
        assert not client._attach_fatal
        assert isinstance(client._display_queue.get_nowait().event, events.NoticeEvent)

    asyncio.run(scenario())


def test_dropped_socket_releases_inflight_operations(monkeypatch: pytest.MonkeyPatch) -> None:
    """A turn submitted right before the drop never gets its OperationFinished;
    leaving it pending would pin the prompt in the busy state forever."""
    _fast_retry(monkeypatch, grace=0.2)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def scenario() -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        client._op_futures["op-1"] = future
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await asyncio.sleep(0.05)
        assert future.done()
        client._closed = True
        await client._cancel_reconnect()

    asyncio.run(scenario())


def _surfaced_events(client: SocketRuntimeClient) -> list[events.Event]:
    surfaced: list[events.Event] = []
    while not client._display_queue.empty():
        surfaced.append(client._display_queue.get_nowait().event)
    return surfaced


def test_reattach_after_a_dropped_turn_settles_the_display(monkeypatch: pytest.MonkeyPatch) -> None:
    """A turn that was streaming when the socket died never delivers its
    TaskFinish, so the reattach has to settle the display itself."""
    _fast_retry(monkeypatch, grace=2.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        client._handshake_ok = True
        client._handshake_settled.set()

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> list[events.Event]:
        client._running = True  # a turn was streaming when the socket died
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task
        return _surfaced_events(client)

    surfaced = asyncio.run(scenario())

    interrupts = [event for event in surfaced if isinstance(event, events.InterruptEvent)]
    assert len(interrupts) == 1
    assert interrupts[0].show_notice is False  # "Interrupted by user" would be a lie
    assert any(isinstance(event, events.NoticeEvent) for event in surfaced)
    assert not client._running


def test_reattach_keeps_the_turn_when_the_server_still_runs_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """A socket that only died from a slow subscriber leaves the turn running on
    the server; the reattach must not claim it was interrupted."""
    _fast_retry(monkeypatch, grace=2.0)
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def fake_connect(*, resume: bool = False) -> None:
        client._handshake_ok = True
        client._handshake_settled.set()
        client._running = True  # the state snapshot still reports a live turn

    monkeypatch.setattr(client, "_connect", fake_connect)

    async def scenario() -> list[events.Event]:
        client._running = True
        client._schedule_reconnect()
        assert client._reconnect_task is not None
        await client._reconnect_task
        return _surfaced_events(client)

    surfaced = asyncio.run(scenario())

    assert not [event for event in surfaced if isinstance(event, events.InterruptEvent)]
    assert client._running


def test_client_reattaches_across_a_server_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end over a real Unix socket: the listener goes away and returns
    on the same path (what a reload does), and the client reattaches with the
    resume handshake instead of detaching."""
    # AF_UNIX paths are capped near 104 bytes, so pytest's tmp_path is too long.
    socket_dir = Path(tempfile.mkdtemp(prefix="klaude-ws-"))
    socket_path = socket_dir / "klaude.sock"
    monkeypatch.setattr(socket_client, "server_socket_path", lambda: socket_path)
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: _TEST_FINGERPRINT)
    _fast_retry(monkeypatch, grace=5.0)

    uris: list[str] = []
    connections: list[Any] = []

    async def scenario() -> None:
        client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
        server = await _serve_handshake_on_unix_socket(socket_path, uris, connections)
        try:
            await client.start()
            await client.wait_for_replay_complete()
            assert client._transcript_loaded

            # The restart: connections and listener go away, then the socket
            # path is rebound by the new process.
            for connection in connections:
                await connection.close()
            server.close()
            await server.wait_closed()
            socket_path.unlink(missing_ok=True)

            for _ in range(200):
                if client._reconnecting:
                    break
                await asyncio.sleep(0.01)
            assert client._reconnecting, "client did not notice the dropped socket"

            server = await _serve_handshake_on_unix_socket(socket_path, uris, connections)
            for _ in range(400):
                if not client._reconnecting:
                    break
                await asyncio.sleep(0.02)
            assert not client._reconnecting, "client never reattached"
            assert not client._connection_lost.is_set()
        finally:
            server.close()
            await server.wait_closed()
            await client.close()

    try:
        asyncio.run(scenario())
    finally:
        shutil.rmtree(socket_dir, ignore_errors=True)

    assert len(uris) == 2, uris
    assert "replay=1" in uris[0]
    assert "resume=1" in uris[1]
