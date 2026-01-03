import io

import pytest

from klaude_code.tui.terminal.notifier import Notification, NotificationType, TerminalNotifier, TerminalNotifierConfig


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:  # pragma: no cover - simple shim
        return True


def _notification() -> Notification:
    return Notification(
        type=NotificationType.AGENT_TASK_COMPLETE,
        title="Task done",
        body="summary text",
    )


def test_notifier_disabled_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY()
    notifier = TerminalNotifier(config=TerminalNotifierConfig(enabled=False, stream=stream))

    sent = notifier.notify(_notification())

    assert sent is False
    assert stream.getvalue() == ""


def test_notifier_sends_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY()
    notifier = TerminalNotifier(config=TerminalNotifierConfig(enabled=True, stream=stream))

    sent = notifier.notify(_notification())

    assert sent is True
    payload = stream.getvalue()
    assert "\033]9;" in payload
    assert "Task done" in payload


def test_env_force_mode_bypasses_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY()
    config = TerminalNotifierConfig.from_env()
    config.stream = stream
    notifier = TerminalNotifier(config=config)

    sent = notifier.notify(_notification())

    assert sent is True
    assert "\033]9;" in stream.getvalue()
