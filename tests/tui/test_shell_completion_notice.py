import asyncio
import io
import json
from typing import Any

import pytest
from rich.console import Console
from rich.segment import Segment

from klaude_code.protocol import events, message, tools
from klaude_code.protocol.models import ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tui.commands import RenderUserMessage
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.components.tools._manage_shell import render_shell_completion
from klaude_code.tui.components.user_input import USER_MESSAGE_MARK
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail

from .test_transcript_rebuild import _welcome
from .test_transcript_toggle import make_envelope, patch_scrollback_writes

pytestmark = pytest.mark.usefixtures("isolated_home")

_REPORT = 'Background shell completion report\n{"output": "RAW OUTPUT BLOB", "tasks": []}'
_TASK_ID = "12345678-1234-5678-9012-123456789abc"


def _task(**changes: Any) -> ShellTaskSnapshot:
    return ShellTaskSnapshot.model_validate(
        {
            "task_id": _TASK_ID,
            "session_id": "main",
            "description": "Run targeted tests",
            "command": "uv run pytest tests/tui -q",
            "work_dir": "/tmp",
            "status": "completed",
            "exit_code": 0,
            "background": True,
            "started_at": 1.0,
            "output_path": "/tmp/shell-output.log",
            **changes,
        }
    )


def _event(tasks: list[ShellTaskSnapshot] | None) -> events.UserMessageEvent:
    event = events.UserMessageEvent(session_id="main", content=_REPORT, source="shell_completion", shell_tasks=tasks)
    return events.UserMessageEvent.model_validate_json(event.model_dump_json())


def _render(event: events.UserMessageEvent, *, detail: Detail = Detail.COMPACT, width: int = 120) -> str:
    renderer = TUICommandRenderer()
    renderer.set_transcript_detail(detail)
    output = io.StringIO()
    renderer.console = Console(file=output, width=width, theme=renderer.themes.app_theme, force_terminal=False)
    asyncio.run(renderer.execute([RenderUserMessage(event)]))
    return output.getvalue()


def _assert_notice(text: str) -> None:
    assert "Shell" in text
    assert USER_MESSAGE_MARK not in text
    assert "Background shell completion report" not in text
    assert "RAW OUTPUT BLOB" not in text
    assert '"output"' not in text
    assert "output_path" not in text
    # Compact mode prints one `› Shell` row per task; full mode keeps a headed block.
    start = text.index("Background results") if "Background results" in text else text.index("› Shell")
    notice = text[start:].split("\n\n", 1)[0]
    assert "✓" not in notice


@pytest.mark.parametrize("count", [1, 3])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_typed_completion_uses_shell_rows_without_report_or_user_input_style(count: int, detail: Detail) -> None:
    tasks = [_task(task_id=f"job-{idx:04d}-long-id", description=f"Run test suite {idx}") for idx in range(count)]
    rendered = _render(_event(tasks), detail=detail)
    _assert_notice(rendered)
    for task in tasks:
        assert task.description in rendered
        assert (task.task_id[:8] in rendered) == (detail == Detail.FULL)
    assert rendered.count("completed") == count
    assert rendered.count("exit 0") == count

    console = Console(width=120, theme=get_theme().app_theme)
    segments = [
        segment for line in console.render_lines(render_shell_completion(tasks, detail=detail)) for segment in line
    ]
    user_background = console.get_style(ThemeKey.USER_INPUT).bgcolor
    assert user_background is not None
    assert all(segment.style is None or segment.style.bgcolor != user_background for segment in segments)
    status_segments = [segment for segment in segments if "completed" in segment.text]
    assert status_segments
    assert all(segment.style == console.get_style(ThemeKey.METADATA_GREEN_DIM) for segment in status_segments)


@pytest.mark.parametrize(
    ("status", "exit_code", "style"),
    [
        ("completed", 2, ThemeKey.ERROR),
        ("failed", 1, ThemeKey.ERROR),
        ("timed_out", -15, ThemeKey.ERROR),
        ("stopped", -15, ThemeKey.METADATA_DIM),
        ("lost", None, ThemeKey.ERROR),
    ],
)
def test_unsuccessful_completion_keeps_status_exit_reason_and_never_claims_success(
    status: str, exit_code: int | None, style: ThemeKey
) -> None:
    task = _task(status=status, exit_code=exit_code, reason="Process no longer available")
    rendered = _render(_event([task]))
    _assert_notice(rendered)
    assert f"Run targeted tests · {status}" in rendered
    assert "Process no longer available" in rendered
    if exit_code is not None:
        assert f"exit {exit_code}" in rendered
    else:
        assert "exit" not in rendered
    console = Console(width=120, theme=get_theme().app_theme)
    status_segments = [
        segment
        for line in console.render_lines(render_shell_completion([task]))
        for segment in line
        if segment.text.strip() == status
    ]
    assert status_segments
    assert all(segment.style == console.get_style(style) for segment in status_segments)


@pytest.mark.parametrize("tasks", [None, []])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_completion_without_metadata_has_short_safe_fallback(
    tasks: list[ShellTaskSnapshot] | None, detail: Detail
) -> None:
    rendered = _render(_event(tasks), detail=detail)
    _assert_notice(rendered)
    assert "Task details unavailable." in rendered
    # Compact reports join the open tool block, so no blank line closes them.
    assert len(rendered.splitlines()) == (2 if detail.is_compact else 3)


@pytest.mark.parametrize("order", ["wait-first", "report-first"])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_compact_wait_prints_only_the_completion_report(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], detail: Detail, order: str
) -> None:
    async def run() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        display._detail.set(detail)  # pyright: ignore[reportPrivateUsage]
        running = _task(status="running", exit_code=None)
        completed = _task()
        finish = events.ToolResultEvent(
            session_id="main",
            tool_call_id="wait-done",
            tool_name=tools.MANAGE_SHELL,
            result="completed",
            status="success",
            ui_extra=ShellTaskUIExtra(action="wait", tasks=[completed]),
        )
        report = _event([completed])
        events_to_send: list[events.Event] = [
            _welcome("main"),
            events.TaskStartEvent(session_id="main", model_id="test-model"),
            events.ToolCallEvent(
                session_id="main",
                tool_call_id="wait-running",
                tool_name=tools.MANAGE_SHELL,
                arguments=json.dumps({"action": "wait", "task_id": _TASK_ID, "wait_ms": 1000}),
                shell_task=running,
            ),
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="wait-running",
                tool_name=tools.MANAGE_SHELL,
                result="still running",
                status="success",
                ui_extra=ShellTaskUIExtra(action="wait", tasks=[running]),
            ),
            events.ToolCallEvent(
                session_id="main",
                tool_call_id="wait-done",
                tool_name=tools.MANAGE_SHELL,
                arguments=json.dumps({"action": "wait", "task_id": _TASK_ID, "wait_ms": 1000}),
                shell_task=completed,
            ),
        ]
        if order == "report-first":
            events_to_send.append(report)
        events_to_send.append(finish)
        if order == "wait-first":
            events_to_send.append(report)
        try:
            for event in events_to_send:
                await display.consume_envelope(make_envelope(event))
            live = capsys.readouterr().out
            if detail.is_compact:
                # The status bar carries the wait; the automatic report carries the result once.
                assert "Waiting for" not in live
                assert live.count("Run targeted tests") == 1
                assert live.count("completed") == 1
                assert "› Shell" in live
                await display.consume_envelope(make_envelope(events.RefreshDisplayEvent(session_id="main")))
                rebuilt = writes[-1][0]
                assert "Waiting for" not in rebuilt
                assert rebuilt.count("Run targeted tests") == 1
                assert rebuilt.count("completed") == 1
            else:
                assert "Waiting for Run targeted tests" in live
                assert "› Shell" in live
        finally:
            await display.stop()

    asyncio.run(run())


def test_compact_legacy_wait_result_also_hides_the_call(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        completed = _task()
        try:
            for event in [
                _welcome("main"),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.ToolCallEvent(
                    session_id="main",
                    tool_call_id="wait-1",
                    tool_name=tools.MANAGE_SHELL,
                    arguments=json.dumps({"action": "wait", "task_id": _TASK_ID, "wait_ms": 1000}),
                    shell_task=completed,
                ),
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="wait-1",
                    tool_name=tools.MANAGE_SHELL,
                    result=completed.model_dump_json(),
                    status="success",
                ),
            ]:
                await display.consume_envelope(make_envelope(event))
            live = capsys.readouterr().out
            # Persisted legacy bodies must take the same compact path.
            assert "Waiting for" not in live
            assert live.count("Run targeted tests") == 1
            assert "completed" in live
        finally:
            await display.stop()

    asyncio.run(run())


@pytest.mark.parametrize("case", ["stopped", "error"])
def test_compact_wait_restores_its_call_when_no_completion_report_follows(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    async def run() -> None:
        patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        stopped = _task(status="stopped", exit_code=-15)
        result = (
            events.ToolResultEvent(
                session_id="main",
                tool_call_id="wait-1",
                tool_name=tools.MANAGE_SHELL,
                result="stopped",
                status="success",
                ui_extra=ShellTaskUIExtra(action="wait", tasks=[stopped]),
            )
            if case == "stopped"
            else events.ToolResultEvent(
                session_id="main",
                tool_call_id="wait-1",
                tool_name=tools.MANAGE_SHELL,
                result="ManageShell error: task not found",
                status="error",
            )
        )
        try:
            for event in [
                _welcome("main"),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.ShellTasksUpdatedEvent(session_id="main", tasks=[stopped]),
                events.ToolCallEvent(
                    session_id="main",
                    tool_call_id="wait-1",
                    tool_name=tools.MANAGE_SHELL,
                    arguments=json.dumps({"action": "wait", "task_id": _TASK_ID, "wait_ms": 1000}),
                ),
                result,
            ]:
                await display.consume_envelope(make_envelope(event))
            live = capsys.readouterr().out
            if case == "stopped":
                # A finished wait prints the one completion row itself.
                assert "› Shell" in live and "stopped · exit -15" in live
                assert "Waiting for" not in live
            else:
                # An error has no completion row, so the call keeps its mark.
                assert "Waiting for Run targeted tests" in live
                assert "task not found" in live
        finally:
            await display.stop()

    asyncio.run(run())


@pytest.mark.parametrize("source", [None, "user", "bash_mode"])
def test_same_report_as_ordinary_user_content_keeps_original_user_style(
    source: message.UserMessageSource | None,
) -> None:
    event = events.UserMessageEvent(session_id="main", content=_REPORT, source=source, shell_tasks=[_task()])
    rendered = _render(event)
    assert USER_MESSAGE_MARK in rendered
    assert "Background shell completion report" in rendered
    assert "RAW OUTPUT BLOB" in rendered
    assert "Run targeted tests" not in rendered
    assert "Background results" not in rendered


def test_batch_is_bounded_in_compact_mode_and_keeps_late_failure_visible() -> None:
    tasks = [_task(task_id=f"task-{idx:03d}-long-id", description=f"Run suite {idx}") for idx in range(16)]
    tasks[-1] = _task(task_id="failure-long-id", description="Important failure", status="failed", exit_code=9)
    compact = _render(_event(tasks))
    _assert_notice(compact)
    assert "Important failure · failed · exit 9" in compact
    assert compact.count("Run suite") == 4
    assert "more 11 tasks" in compact
    assert len(compact.splitlines()) == 6
    full = _render(_event(tasks), detail=Detail.FULL)
    assert full.count("Run suite") == 9
    assert "more 6 tasks" in full
    assert "Important failure failure-long-id · failed · exit 9" in full


@pytest.mark.parametrize("width", [12, 24, 120])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_narrow_unicode_and_markup_are_literal_and_fit_terminal(width: int, detail: Detail) -> None:
    task = _task(description="[red]测试[/red]", reason="[bold]原因[/bold]")
    console = Console(width=width, theme=get_theme().app_theme)
    lines = console.render_lines(render_shell_completion([task], detail=detail), pad=False)
    assert all(Segment.get_line_length(line) <= width for line in lines)
    text = "".join(segment.text.strip() for line in lines for segment in line)
    # Compact report rows clip a long subject to two lines; the markup stays literal either way.
    clipped = detail.is_compact and width < 120
    assert ("[red]测" if clipped else "[red]测试[/red]") in text
    assert "[bold]原因[/bold]" in text
    assert ("12345678" in text) == (detail == Detail.FULL)
    if width == 120:
        description_segments = [segment for line in lines for segment in line if "[red]" in segment.text]
        assert description_segments
        assert all(
            segment.style == console.get_style(ThemeKey.BASH_TOOL_DESCRIPTION) for segment in description_segments
        )


@pytest.mark.parametrize("count", [1, 16])
def test_display_tape_toggle_refresh_and_following_stream_preserve_notice_and_spacing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], count: int
) -> None:
    async def run() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        tasks = [_task(task_id=f"task-{idx:03d}-long-id", description=f"Run suite {idx}") for idx in range(count)]
        try:
            for event in [
                _welcome("main"),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.AssistantTextStartEvent(session_id="main"),
                events.AssistantTextDeltaEvent(session_id="main", content="Before notification."),
                events.AssistantTextEndEvent(session_id="main"),
                _event(tasks),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
                events.AssistantTextStartEvent(session_id="main"),
                events.AssistantTextDeltaEvent(session_id="main", content="After notification."),
                events.AssistantTextEndEvent(session_id="main"),
                events.ToolCallEvent(
                    session_id="main", tool_call_id="next-tool", tool_name=tools.BASH, arguments='{"command":"pwd"}'
                ),
                events.ToolResultEvent(
                    session_id="main",
                    tool_call_id="next-tool",
                    tool_name=tools.BASH,
                    result="NEXT OUTPUT",
                    status="success",
                ),
            ]:
                await display.consume_envelope(make_envelope(event))
            live = capsys.readouterr().out
            _assert_notice(live)
            lines = [line.rstrip() for line in live.splitlines()]
            before = next(idx for idx, line in enumerate(lines) if "Before notification." in line)
            header = next(idx for idx, line in enumerate(lines) if "› Shell" in line)
            after = next(idx for idx, line in enumerate(lines) if "After notification." in line)
            assert lines[before + 1 : header] == [""]
            assert lines[after - 1] == ""
            assert lines[before].startswith("● ")
            assert lines[after].startswith("● ")

            await display.consume_envelope(make_envelope(events.RefreshDisplayEvent(session_id="main")))
            refreshed, cleared = writes[-1]
            assert cleared
            assert (
                refreshed[refreshed.index("● Before notification.") :] == live[live.index("● Before notification.") :]
            )
            await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id="main")))
            _assert_notice(writes[-1][0])
            assert "Run suite 0" in writes[-1][0]
            assert "task-000-long-id" in writes[-1][0]
            await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id="main")))
            assert writes[-1][0] == refreshed
            await display.consume_envelope(make_envelope(events.RefreshDisplayEvent(session_id="main")))
            assert writes[-1][0] == refreshed
            for event in [
                events.AssistantTextStartEvent(session_id="main"),
                events.AssistantTextDeltaEvent(session_id="main", content="Continue after rebuild."),
                events.AssistantTextEndEvent(session_id="main"),
            ]:
                await display.consume_envelope(make_envelope(event))
            continued = capsys.readouterr().out
            assert "Continue after rebuild." in continued
            assert "RAW OUTPUT BLOB" not in continued
        finally:
            await display.stop()

    asyncio.run(run())
