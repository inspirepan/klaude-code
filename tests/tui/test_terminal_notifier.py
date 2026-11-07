import asyncio
import io

import pytest

from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.terminal import title as terminal_title
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
    assert notifier.enabled is False
    assert stream.getvalue() == ""


def test_notifier_sends_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY()
    notifier = TerminalNotifier(config=TerminalNotifierConfig(enabled=True, stream=stream))

    sent = notifier.notify(_notification())

    assert sent is True
    payload = stream.getvalue()
    assert "\033]777;notify;" in payload
    assert "summary text" in payload


@pytest.mark.parametrize("tty", [True, False])
def test_locate_display_emits_notification_and_cleans_up_title(monkeypatch: pytest.MonkeyPatch, tty: bool) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY() if tty else io.StringIO()
    monkeypatch.setattr(terminal_title.sys, "__stdout__", stream)
    display = TUIDisplay(notifier=TerminalNotifier(TerminalNotifierConfig(stream=stream)))

    async def run() -> None:
        terminal_title.update_terminal_title(session_title="Original")
        display.locate_session()
        if tty:
            assert "● HERE" in stream.getvalue()
            assert "\033]777;notify;klaude;Session open in this terminal\033\\" in stream.getvalue()
        else:
            assert stream.getvalue() == ""
        await display.stop()
        assert terminal_title._locate_handle is None
        assert "HERE" not in stream.getvalue().rsplit("\033]0;", 1)[-1]

    asyncio.run(run())


def test_env_force_mode_bypasses_focus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TERM", "xterm-256color")
    stream = FakeTTY()
    config = TerminalNotifierConfig.from_env()
    config.stream = stream
    notifier = TerminalNotifier(config=config)

    sent = notifier.notify(_notification())

    assert sent is True
    assert "\033]777;notify;" in stream.getvalue()


@pytest.mark.parametrize("writable,draining", [(False, False), (True, True)])
def test_locate_skips_notification_when_terminal_busy(
    monkeypatch: pytest.MonkeyPatch, writable: bool, draining: bool
) -> None:
    stream = FakeTTY()
    monkeypatch.setattr(terminal_title, "_try_write_title", lambda _title: False)
    monkeypatch.setattr("klaude_code.tui.display.stdout_writable", lambda: writable)
    monkeypatch.setattr("klaude_code.tui.display.scrollback_write_in_flight", lambda: draining)
    display = TUIDisplay(notifier=TerminalNotifier(TerminalNotifierConfig(stream=stream)))

    async def run() -> None:
        display.locate_session()
        assert stream.getvalue() == ""
        await display.stop()

    asyncio.run(run())
