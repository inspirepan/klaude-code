from __future__ import annotations

import asyncio

import pytest

from klaude_code.control.runtime.actor import SessionActorSnapshot, SessionConfig
from klaude_code.server import prevent_sleep


class _FakeProcess:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def _snapshot(*, running: bool, pending_requests: int = 0) -> SessionActorSnapshot:
    from klaude_code.control.runtime.actor import RootTaskState

    root = RootTaskState(operation_id="op", task_id="task", kind="agent") if running else None
    return SessionActorSnapshot(
        session_id="session",
        active_root_task=root,
        child_task_count=0,
        pending_request_count=pending_requests,
        is_idle=not running and pending_requests == 0,
        config=SessionConfig(),
    )


def test_monitor_holds_assertion_only_while_running(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(prevent_sleep, "_is_macos", lambda: True)
    monkeypatch.setattr(prevent_sleep, "start_prevent_sleep", lambda: calls.append("start"))
    monkeypatch.setattr(prevent_sleep, "stop_prevent_sleep", lambda: calls.append("stop"))

    snapshots: list[SessionActorSnapshot] = []
    poll_count = 0

    def _provider() -> list[SessionActorSnapshot]:
        nonlocal poll_count
        poll_count += 1
        return list(snapshots)

    async def _wait_polls(n: int) -> None:
        target = poll_count + n
        while poll_count < target:
            await asyncio.sleep(0.001)

    async def _run() -> None:
        task = asyncio.create_task(prevent_sleep.run_prevent_sleep_monitor(_provider, poll_interval=0.001))

        await _wait_polls(2)
        assert calls == []

        snapshots.append(_snapshot(running=True))
        await _wait_polls(2)
        assert calls == ["start"]

        # A session blocked on user interaction must release the assertion.
        snapshots[0] = _snapshot(running=True, pending_requests=1)
        await _wait_polls(2)
        assert calls == ["start", "stop"]

        snapshots[0] = _snapshot(running=True)
        await _wait_polls(2)
        assert calls == ["start", "stop", "start"]

        # Cancellation while active releases the assertion.
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert calls == ["start", "stop", "start", "stop"]

    asyncio.run(_run())


def test_monitor_exits_immediately_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prevent_sleep, "_is_macos", lambda: False)

    def _provider() -> list[SessionActorSnapshot]:
        raise AssertionError("provider must not be polled off macOS")

    asyncio.run(prevent_sleep.run_prevent_sleep_monitor(_provider, poll_interval=0.001))


def test_exit_signal_handler_does_not_acquire_prevent_sleep_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess()
    sent_signals: list[tuple[int, int]] = []

    monkeypatch.setattr(prevent_sleep, "_caffeinate_process", process)
    monkeypatch.setattr(prevent_sleep.os, "getpid", lambda: 123)
    monkeypatch.setattr(prevent_sleep.os, "kill", lambda pid, signum: sent_signals.append((pid, signum)))
    monkeypatch.setattr(prevent_sleep.signal, "signal", lambda signum, _handler: None)

    with prevent_sleep._lock:
        prevent_sleep._handle_exit_signal(15, None)

    assert process.killed is True
    assert prevent_sleep._caffeinate_process is None
    assert sent_signals == [(123, 15)]


def test_exit_signal_handler_ignores_missing_caffeinate(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_signals: list[tuple[int, int]] = []

    monkeypatch.setattr(prevent_sleep, "_caffeinate_process", None)
    monkeypatch.setattr(prevent_sleep.os, "getpid", lambda: 123)
    monkeypatch.setattr(prevent_sleep.os, "kill", lambda pid, signum: sent_signals.append((pid, signum)))
    monkeypatch.setattr(prevent_sleep.signal, "signal", lambda signum, _handler: None)

    prevent_sleep._handle_exit_signal(15, None)

    assert sent_signals == [(123, 15)]
