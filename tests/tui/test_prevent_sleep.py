from __future__ import annotations

import pytest

from klaude_code.tui.terminal import prevent_sleep


class _FakeProcess:
    def __init__(self) -> None:
        self.killed = False

    def kill(self) -> None:
        self.killed = True


def test_exit_signal_handler_does_not_acquire_prevent_sleep_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    process = _FakeProcess()
    sent_signals: list[tuple[int, int]] = []

    monkeypatch.setattr(prevent_sleep, "_caffeinate_process", process)
    monkeypatch.setattr(prevent_sleep.os, "getpid", lambda: 123)
    monkeypatch.setattr(prevent_sleep.os, "kill", lambda pid, signum: sent_signals.append((pid, signum)))
    monkeypatch.setattr(prevent_sleep.signal, "signal", lambda signum, handler: None)

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
    monkeypatch.setattr(prevent_sleep.signal, "signal", lambda signum, handler: None)

    prevent_sleep._handle_exit_signal(15, None)

    assert sent_signals == [(123, 15)]
