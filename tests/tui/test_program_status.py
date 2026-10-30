import asyncio
import io
from collections.abc import Callable

import pytest

import klaude_code.tui.terminal.program_status as status_module
from klaude_code.tui.terminal.program_status import ProgramStatusReporter


class FakeTTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def terminal(monkeypatch: pytest.MonkeyPatch) -> FakeTTY:
    stream = FakeTTY()
    monkeypatch.setattr(status_module.sys, "__stdout__", stream)
    monkeypatch.setattr(status_module, "stdout_writable", lambda: True)
    monkeypatch.setattr(status_module, "scrollback_write_in_flight", lambda: False)
    monkeypatch.setattr(status_module, "_RETRY_SECONDS", 0.001)
    return stream


async def wait_until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0.001)


def test_lifecycle_priority_deduplication_and_close(terminal: FakeTTY) -> None:
    async def _test() -> None:
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        try:
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 1)
            reporter.report_session_state("s1", "working")
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 2)
            reporter.report_session_state("s1", "working")
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 2
            reporter.report_session_state("s2", "needs_you")
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 3)
            reporter.report_session_state("s1", "idle")
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 3
            reporter.report_session_state("s1", "working")
            reporter.report_session_state("s2", "idle")
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 4)
            reporter.report_session_state("s1", "idle")
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 5)
        finally:
            await reporter.close()
        reporter.report_session_state("s1", "working")
        await reporter.close()
        await asyncio.sleep(0.01)
        assert terminal.getvalue() == (
            "\x1b]7501;state=idle:app=klaude\x1b\\"
            "\x1b]7501;state=working:app=klaude\x1b\\"
            "\x1b]7501;state=blocked:app=klaude\x1b\\"
            "\x1b]7501;state=working:app=klaude\x1b\\"
            "\x1b]7501;state=idle:app=klaude\x1b\\"
            "\x1b]7501;state=clear\x1b\\"
        )

    asyncio.run(_test())


def test_factory_needs_only_tty_and_uses_real_stdout(terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("HERDR_ENV", "HERDR_SOCKET_PATH", "HERDR_PANE_ID", "HC_TERMINAL_ID", "TERM_PROGRAM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TERM", "dumb")
    proxy = io.StringIO()
    monkeypatch.setattr(status_module.sys, "stdout", proxy)

    async def _test() -> None:
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        try:
            await wait_until(lambda: bool(terminal.getvalue()))
        finally:
            await reporter.close()
        assert proxy.getvalue() == ""
        monkeypatch.setattr(status_module.sys, "__stdout__", None)
        assert ProgramStatusReporter.from_terminal() is None
        assert proxy.getvalue() == ""
        monkeypatch.setattr(status_module.sys, "stdout", terminal)
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        await reporter.close()

    asyncio.run(_test())


@pytest.mark.parametrize("guard", ["stdout_writable", "scrollback_write_in_flight"])
def test_busy_retries_latest_state_and_clear(terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch, guard: str) -> None:
    busy = True
    monkeypatch.setattr(status_module, guard, lambda: not busy if guard == "stdout_writable" else busy)

    async def _test() -> None:
        nonlocal busy
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        try:
            reporter.report_session_state("s1", "working")
            reporter.report_session_state("s1", "needs_you")
            await asyncio.sleep(0.01)
            assert terminal.getvalue() == ""
            busy = False
            await wait_until(lambda: bool(terminal.getvalue()))
            assert terminal.getvalue() == "\x1b]7501;state=blocked:app=klaude\x1b\\"
            busy = True
            reporter.report_session_state("s1", "working")
            reporter.report_session_state("s1", "idle")
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 1
            busy = False
            await wait_until(lambda: terminal.getvalue().endswith("state=idle:app=klaude\x1b\\"))
            busy = True
            close_task = asyncio.create_task(reporter.close())
            await asyncio.sleep(0.01)
            assert not close_task.done()
            assert "state=clear" not in terminal.getvalue()
            reporter.report_session_state("s1", "working")
            busy = False
            await close_task
            assert terminal.getvalue() == (
                "\x1b]7501;state=blocked:app=klaude\x1b\\"
                "\x1b]7501;state=idle:app=klaude\x1b\\"
                "\x1b]7501;state=clear\x1b\\"
            )
        finally:
            await reporter.close()

    asyncio.run(_test())


def test_close_is_bounded_and_stops_retrying(terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(status_module, "stdout_writable", lambda: False)
    monkeypatch.setattr(status_module, "_CLOSE_TIMEOUT_SECONDS", 0.01)

    async def _test() -> None:
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        await asyncio.wait_for(reporter.close(), timeout=1)
        assert reporter._worker.done()  # pyright: ignore[reportPrivateUsage]
        monkeypatch.setattr(status_module, "stdout_writable", lambda: True)
        reporter.report_session_state("s1", "working")
        await asyncio.sleep(0.01)
        assert terminal.getvalue() == ""

    asyncio.run(_test())


@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("error", [OSError, ValueError])
def test_write_failures_are_logged_and_retried(
    terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch, operation: str, error: type[Exception]
) -> None:
    original = getattr(terminal, operation)
    failed = False
    logs: list[str] = []

    def fail_once(*args: object) -> object:
        nonlocal failed
        if not failed:
            failed = True
            raise error("fake terminal failure")
        return original(*args)

    monkeypatch.setattr(terminal, operation, fail_once)
    monkeypatch.setattr(status_module, "log_debug", lambda message, **kwargs: logs.append(message))

    async def _test() -> None:
        reporter = ProgramStatusReporter.from_terminal()
        assert reporter is not None
        try:
            await wait_until(lambda: failed and reporter._sent_state == "idle")  # pyright: ignore[reportPrivateUsage]
        finally:
            await reporter.close()
        assert any("Program status write failed:" in message for message in logs)
        assert terminal.getvalue().endswith("\x1b]7501;state=clear\x1b\\")

    asyncio.run(_test())
