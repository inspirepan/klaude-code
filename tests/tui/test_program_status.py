import asyncio
import base64
import io
from collections.abc import Callable

import pytest
from prompt_toolkit.input.vt100_parser import Vt100Parser
from prompt_toolkit.key_binding.key_processor import KeyPress

import klaude_code.tui.terminal.program_status as status_module
from klaude_code.protocol import events
from klaude_code.protocol.models.session_status import (
    SessionAttention,
    SessionOwnedTasks,
    SessionStatus,
    SessionTurnResult,
)
from klaude_code.protocol.user_interaction import (
    AskUserQuestionQuestion,
    AskUserQuestionRequestPayload,
    OperationSelectRequestPayload,
)
from klaude_code.tui.client.base import SessionInfoSnapshot
from klaude_code.tui.client.socket_client import SocketRuntimeClient
from klaude_code.tui.input.program_status import ProgramStatusParser
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
            reporter.report_session_state("s1", SessionStatus(category="working"))
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 2)
            reporter.report_session_state("s1", SessionStatus(category="working"))
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 2
            reporter.report_session_state("s2", SessionStatus(category="needs_you"))
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 3)
            reporter.report_session_state("s1", SessionStatus())
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 3
            reporter.report_session_state("s1", SessionStatus(category="working"))
            reporter.report_session_state("s2", SessionStatus())
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 4)
            reporter.report_session_state("s1", SessionStatus())
            await wait_until(lambda: terminal.getvalue().count("\x1b]7501;") == 5)
        finally:
            await reporter.close()
        reporter.report_session_state("s1", SessionStatus(category="working"))
        await reporter.close()
        await asyncio.sleep(0.01)
        assert terminal.getvalue() == (
            "\x1b]7501;state=idle:app=klaude\x1b\\"
            "\x1b]7501;state=working:app=klaude\x1b\\"
            "\x1b]7501;state=blocked:app=klaude:msg=SW5wdXQgcmVxdWlyZWQ=\x1b\\"
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
            reporter.report_session_state("s1", SessionStatus(category="working"))
            reporter.report_session_state("s1", SessionStatus(category="needs_you"))
            await asyncio.sleep(0.01)
            assert terminal.getvalue() == ""
            busy = False
            await wait_until(lambda: bool(terminal.getvalue()))
            assert terminal.getvalue() == "\x1b]7501;state=blocked:app=klaude:msg=SW5wdXQgcmVxdWlyZWQ=\x1b\\"
            busy = True
            reporter.report_session_state("s1", SessionStatus(category="working"))
            reporter.report_session_state("s1", SessionStatus())
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;") == 1
            busy = False
            await wait_until(lambda: terminal.getvalue().endswith("state=idle:app=klaude\x1b\\"))
            busy = True
            close_task = asyncio.create_task(reporter.close())
            await asyncio.sleep(0.01)
            assert not close_task.done()
            assert "state=clear" not in terminal.getvalue()
            reporter.report_session_state("s1", SessionStatus(category="working"))
            busy = False
            await close_task
            assert terminal.getvalue() == (
                "\x1b]7501;state=blocked:app=klaude:msg=SW5wdXQgcmVxdWlyZWQ=\x1b\\"
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
        reporter.report_session_state("s1", SessionStatus(category="working"))
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
            await wait_until(lambda: failed and reporter._sent_state == "state=idle:app=klaude")  # pyright: ignore[reportPrivateUsage]
        finally:
            await reporter.close()
        assert any("Program status write failed:" in message for message in logs)
        assert terminal.getvalue().endswith("\x1b]7501;state=clear\x1b\\")

    asyncio.run(_test())


@pytest.mark.parametrize("result, expected", [("succeeded", "done"), ("failed", "error"), ("interrupted", "idle")])
def test_new_turn_results_wait_for_background_and_latch(terminal: FakeTTY, result: str, expected: str) -> None:
    async def _test() -> None:
        reporter = ProgramStatusReporter(terminal)
        old = SessionTurnResult(id="old", result="succeeded")
        reporter.report_session_state("s", SessionStatus(last_turn=old), snapshot=True)
        await wait_until(lambda: bool(terminal.getvalue()))
        assert "state=done" not in terminal.getvalue()
        reporter.report_session_state("s", SessionStatus(category="working", execution="running", last_turn=old))
        await wait_until(lambda: "state=working" in terminal.getvalue())
        turn = SessionTurnResult.model_validate({"id": "new", "result": result})
        reporter.report_session_state("s", SessionStatus(last_turn=turn, owned=SessionOwnedTasks(active_shells=1)))
        await asyncio.sleep(0.01)
        assert "state=done" not in terminal.getvalue()
        reporter.report_session_state("s", SessionStatus(last_turn=turn))
        await wait_until(lambda: terminal.getvalue().endswith(f"state={expected}:app=klaude\x1b\\"))
        output = terminal.getvalue()
        reporter.report_session_state("s", SessionStatus(last_turn=turn))
        await asyncio.sleep(0.01)
        assert terminal.getvalue() == output
        reporter.report_session_state("s", SessionStatus(category="working", execution="running", last_turn=turn))
        await wait_until(lambda: terminal.getvalue() != output)
        assert terminal.getvalue().endswith("state=working:app=klaude\x1b\\")
        await reporter.close()

    asyncio.run(_test())


def test_structured_attention_and_payload_changes(terminal: FakeTTY) -> None:
    async def _test() -> None:
        reporter = ProgramStatusReporter(terminal)
        try:
            attention = SessionAttention(kind="needs_input", code="tool", source_session_id="child", request_id="r")
            reporter.report_session_state("s", SessionStatus(category="needs_you", attention=[attention]))
            await wait_until(lambda: "state=blocked" in terminal.getvalue())
            assert "kind=" not in terminal.getvalue()
            request = events.UserInteractionRequestEvent(
                session_id="child",
                request_id="r",
                source="tool",
                payload=AskUserQuestionRequestPayload(
                    questions=[
                        AskUserQuestionQuestion(id="q", header="choice", question="Continue?\n\x1b安全", options=[])
                    ]
                ),
            )
            reporter.report_interaction(request)
            await wait_until(lambda: "kind=question" in terminal.getvalue())
            assert base64.b64encode("Continue? 安全".encode()).decode() in terminal.getvalue()
            request = request.model_copy(
                update={
                    "payload": OperationSelectRequestPayload(header="Select", question="Authorize?", options=[]),
                    "source": "approval",
                }
            )
            reporter.report_interaction(request)
            await wait_until(lambda: "kind=permission" in terminal.getvalue())
            assert base64.b64encode(b"Authorize?").decode() in terminal.getvalue()
            reporter.report_session_state(
                "s",
                SessionStatus(
                    category="needs_you",
                    attention=[
                        SessionAttention(
                            kind="error", code="execution_failed", source_session_id="s", message="Fatal failure"
                        )
                    ],
                ),
            )
            await wait_until(lambda: "state=error" in terminal.getvalue())
            record = terminal.getvalue().split("\x1b]7501;")[-1]
            assert "kind=" not in record
            assert base64.b64encode(b"Fatal failure").decode() in record
        finally:
            await reporter.close()

    asyncio.run(_test())


def test_detection_is_positive_only_and_respects_kinds(terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch) -> None:
    supported: list[bool] = []
    monkeypatch.setattr(status_module, "set_native_status_supported", supported.append)

    async def _test() -> None:
        reporter = ProgramStatusReporter(terminal)
        try:
            reporter.start_detection()
            await wait_until(lambda: "\x1b]7501;?\x1b\\" in terminal.getvalue())
            assert supported == []
            keys: list[KeyPress] = []
            parser = ProgramStatusParser(Vt100Parser(keys.append), reporter.receive_capabilities)
            parser.feed("\x1b]7501; ? : states = idle, working,done,blocked,error : kinds = question : ext=x\x07")
            parser.flush()
            assert keys == []
            assert supported == [True]
            reporter.report_session_state(
                "s",
                SessionStatus(
                    category="needs_you",
                    attention=[SessionAttention(kind="needs_input", code="approval", source_session_id="s")],
                ),
            )
            await wait_until(lambda: "state=blocked" in terminal.getvalue())
            assert "kind=permission" not in terminal.getvalue()
            assert "msg=" in terminal.getvalue()
            parser.feed("\x1b]7501;?:states=idle,working\x1b\\")
            assert supported == [True, False]
        finally:
            await reporter.close()

    asyncio.run(_test())


def test_probe_retries_busy_tty_and_bare_reply_enables_titles(
    terminal: FakeTTY, monkeypatch: pytest.MonkeyPatch
) -> None:
    busy = True
    supported: list[bool] = []
    monkeypatch.setattr(status_module, "stdout_writable", lambda: not busy)
    monkeypatch.setattr(status_module, "set_native_status_supported", supported.append)

    async def _test() -> None:
        nonlocal busy
        reporter = ProgramStatusReporter(terminal)
        try:
            reporter.start_detection()
            reporter.report_session_state("s", SessionStatus(category="working"))
            await asyncio.sleep(0.01)
            assert terminal.getvalue() == ""
            busy = False
            await wait_until(lambda: "state=working" in terminal.getvalue())
            assert terminal.getvalue().startswith("\x1b]7501;?\x1b\\")
            reporter.receive_capabilities("\x1b]7501;?\x1b\\")
            assert supported == [True]
            reporter.start_detection()
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("\x1b]7501;?") == 1
        finally:
            await reporter.close()

    asyncio.run(_test())


def test_interaction_clears_old_completion_and_bounds_message(terminal: FakeTTY) -> None:
    async def _test() -> None:
        reporter = ProgramStatusReporter(terminal)
        try:
            reporter.report_session_state("s", SessionStatus(), snapshot=True)
            turn = SessionTurnResult(id="new", result="succeeded")
            reporter.report_session_state("s", SessionStatus(last_turn=turn))
            await wait_until(lambda: "state=done" in terminal.getvalue())
            reporter.report_session_state(
                "s",
                SessionStatus(
                    last_turn=turn,
                    category="needs_you",
                    attention=[
                        SessionAttention(
                            kind="needs_input", code="approval", source_session_id="s", message="汉" * 1000 + "\n\x07"
                        )
                    ],
                ),
            )
            await wait_until(lambda: "state=blocked" in terminal.getvalue())
            encoded = terminal.getvalue().split(":msg=")[-1].removesuffix("\x1b\\")
            msg = base64.b64decode(encoded).decode("utf-8")
            assert len(msg.encode()) <= 2048
            assert all(char.isprintable() for char in msg)
            reporter.report_session_state("s", SessionStatus(last_turn=turn))
            await wait_until(lambda: terminal.getvalue().endswith("state=idle:app=klaude\x1b\\"))
            assert terminal.getvalue().count("state=done") == 1
            reporter.report_session_state("other", SessionStatus(last_turn=turn), snapshot=True)
            await asyncio.sleep(0.01)
            assert terminal.getvalue().count("state=done") == 1
        finally:
            await reporter.close()

    asyncio.run(_test())


def test_attach_snapshots_but_not_live_info_refresh_baseline_results(terminal: FakeTTY) -> None:
    async def _test() -> None:
        reporter = ProgramStatusReporter(terminal)

        def on_info(info: SessionInfoSnapshot) -> None:
            if info.is_replay_snapshot:
                reporter.report_session_state(info.session_id, info.status, snapshot=True)

        async def on_envelope(envelope: events.EventEnvelope) -> None:
            if isinstance(envelope.event, events.SessionStatusEvent) and envelope.event_seq > 0:
                reporter.report_session_state(envelope.session_id, envelope.event.status)

        client = SocketRuntimeClient("s", on_envelope=on_envelope, on_session_info=on_info)
        try:
            frame = {
                "type": "session_info",
                "session_id": "s",
                "status": {"last_turn": {"id": "old", "result": "succeeded"}},
            }
            await client._handle_frame(frame)  # pyright: ignore[reportPrivateUsage]
            frame["status"] = {"last_turn": {"id": "second_snapshot", "result": "succeeded"}}
            await client._handle_frame(frame)  # pyright: ignore[reportPrivateUsage]
            while not client._display_queue.empty():  # pyright: ignore[reportPrivateUsage]
                await on_envelope(client._display_queue.get_nowait())  # pyright: ignore[reportPrivateUsage]
            await wait_until(lambda: bool(terminal.getvalue()))
            assert "state=done" not in terminal.getvalue()
            await client._handle_frame({"type": "replay_complete"})  # pyright: ignore[reportPrivateUsage]
            turn = SessionTurnResult(id="new", result="succeeded")
            live = events.EventEnvelope(
                event_id="live",
                event_seq=1,
                session_id="s",
                event_type="session.status",
                durability="ephemeral",
                timestamp=0,
                event=events.SessionStatusEvent(session_id="s", status=SessionStatus(last_turn=turn)),
            )
            await on_envelope(live)
            await wait_until(lambda: "state=done" in terminal.getvalue())
            output = terminal.getvalue()
            frame["status"] = {"last_turn": turn.model_dump()}
            await client._handle_frame(frame)  # pyright: ignore[reportPrivateUsage]
            while not client._display_queue.empty():  # pyright: ignore[reportPrivateUsage]
                await on_envelope(client._display_queue.get_nowait())  # pyright: ignore[reportPrivateUsage]
            await asyncio.sleep(0.01)
            assert terminal.getvalue() == output
        finally:
            await reporter.close()

    asyncio.run(_test())
