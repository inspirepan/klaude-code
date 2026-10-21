import io
import json
from typing import Any, Literal

import pytest
from rich.console import Console, RenderableType

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskOutput, ShellTaskSnapshot
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.components.tools import FULL_TOOL_RESULT_MAX_LINES, render_tool_call, render_tool_result
from klaude_code.tui.components.tools._manage_shell import extract_shell_task_ui_extra
from klaude_code.tui.components.tools._presentation import (
    get_tool_active_form,
    get_tool_call_presentation,
    get_tool_display_name,
)
from klaude_code.tui.components.tools.compact import render_compact_tool_activity, render_compact_tool_result
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail

_TASK_ID = "12345678-1234-5678-9012-123456789abc"


def _task(**changes: Any) -> ShellTaskSnapshot:
    return ShellTaskSnapshot.model_validate(
        {
            "task_id": _TASK_ID,
            "session_id": "main",
            "description": "Run targeted tests",
            "command": "uv run pytest tests/tui -q",
            "work_dir": "/tmp",
            "status": "running",
            "background": True,
            "started_at": 1.0,
            "output_path": "/tmp/shell-output.log",
            **changes,
        }
    )


def _event(
    ui_extra: ShellTaskUIExtra | None = None,
    *,
    result: str = "Model-facing text must not be displayed",
    status: Literal["success", "error", "aborted"] = "success",
) -> events.ToolResultEvent:
    return events.ToolResultEvent(
        session_id="main",
        tool_call_id="manage-1",
        tool_name=tools.MANAGE_SHELL,
        result=result,
        status=status,
        ui_extra=ui_extra,
    )


def _console(*, width: int = 120) -> Console:
    return Console(file=io.StringIO(), width=width, record=True, force_terminal=False, theme=get_theme().app_theme)


def _render(renderable: RenderableType | None, *, width: int = 120) -> str:
    assert renderable is not None
    console = _console(width=width)
    console.print(renderable)
    return console.export_text()


@pytest.mark.parametrize("action", ["wait", "output", "stop", "list"])
def test_call_dispatch_uses_shell_rows_and_description_hint(action: str) -> None:
    event = events.ToolCallEvent(
        session_id="main",
        tool_call_id="manage-1",
        tool_name=tools.MANAGE_SHELL,
        arguments=json.dumps({"action": action, "task_id": _TASK_ID, "wait_ms": 10000, "limit": 16384, "offset": 0}),
    )
    rendered = _render(render_tool_call(event, shell_task=_task()))
    assert "$ Shell" in rendered
    assert ("Waiting for" if action == "wait" else action.title()) in rendered
    if action != "list":
        # The description names the task, so its ID stays out of the transcript.
        assert "Run targeted tests" in rendered and "12345678" not in rendered
    else:
        assert "Run targeted tests" not in rendered
    assert _TASK_ID not in rendered
    assert "limit" not in rendered
    assert "wait_ms" not in rendered
    assert "offset" not in rendered


def test_call_command_fallback_and_nondefault_operation_options() -> None:
    event = events.ToolCallEvent(
        session_id="main",
        tool_call_id="manage-1",
        tool_name=tools.MANAGE_SHELL,
        arguments=json.dumps({"action": "wait", "task_id": _TASK_ID, "wait_ms": 120000}),
    )
    rendered = _render(render_tool_call(event, shell_task=_task(description="")))
    assert "Waiting for uv run pytest tests/tui -q" in rendered and "12345678" not in rendered
    assert "120s" in rendered
    event.arguments = json.dumps({"action": "output", "task_id": _TASK_ID, "offset": 42000, "wait_ms": 120000})
    rendered = _render(render_tool_call(event))
    assert "Output 12345678" in rendered
    assert "offset 42000" in rendered
    assert "120s" not in rendered


def test_presentation_and_activity_share_shell_identity_and_hint() -> None:
    arguments = json.dumps({"action": "wait", "task_id": _TASK_ID})
    assert get_tool_display_name(tools.MANAGE_SHELL) == "Shell"
    assert get_tool_active_form(tools.MANAGE_SHELL) == "Managing Shell"
    assert get_tool_call_presentation(tools.MANAGE_SHELL, arguments).subject == "Wait 12345678"
    activity = render_compact_tool_activity(tools.MANAGE_SHELL, arguments, shell_task=_task(), status="success")
    assert activity.plain == "Shell Waiting for Run targeted tests"
    assert "✓" not in activity.plain
    clipped = render_compact_tool_activity(tools.MANAGE_SHELL, arguments, shell_task=_task(), max_target_chars=18)
    assert clipped.plain == "Shell Waiting for Run t…"


@pytest.mark.parametrize("action", ["list", "output", "wait", "stop"])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_result_dispatch_renders_ui_extra_without_model_text(action: str, detail: Detail) -> None:
    ui_extra = ShellTaskUIExtra.model_validate({"action": action, "tasks": [_task().model_dump()]})
    if detail.is_compact:
        # Successful operations add no result details; pending waits also stay quiet.
        assert render_tool_result(_event(ui_extra), detail=detail) is None
        return
    rendered = _render(render_tool_result(_event(ui_extra), detail=detail))
    assert ("Run targeted tests" in rendered) == (action == "list")
    assert "running" in rendered
    assert "Model-facing" not in rendered
    assert "output_path" not in rendered
    assert "session_id" not in rendered
    if action != "list":
        assert "12345678" not in rendered
        assert "uv run pytest tests/tui -q" not in rendered
    elif detail == Detail.FULL:
        assert _TASK_ID in rendered
        assert "uv run pytest tests/tui -q" in rendered
    else:
        assert _TASK_ID not in rendered
        assert "12345678" not in rendered


@pytest.mark.parametrize("has_snapshot", [False, True])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
@pytest.mark.parametrize("legacy", [False, True])
def test_renderer_only_omits_identity_already_shown_in_call(has_snapshot: bool, detail: Detail, legacy: bool) -> None:
    renderer = TUICommandRenderer()
    renderer.console = _console()
    renderer.set_transcript_detail(detail)
    task = _task(status="completed", exit_code=0)
    call = events.ToolCallEvent(
        session_id="main",
        tool_call_id="manage-1",
        tool_name=tools.MANAGE_SHELL,
        arguments=json.dumps({"action": "wait", "task_id": _TASK_ID}),
    )
    assert renderer.display_tool_call(call, shell_task=task if has_snapshot else None)
    result = _event(result=task.model_dump_json()) if legacy else _event(ShellTaskUIExtra(action="wait", tasks=[task]))
    assert renderer.display_tool_call_result(result)
    rendered = renderer.console.export_text()
    if detail.is_compact:
        # The wait result is itself the `› Shell` completion row.
        assert "› Shell" in rendered
        assert "Run targeted tests" in rendered
    else:
        assert rendered.count("Run targeted tests") == 1
    assert "completed · exit 0" in rendered
    assert ("uv run pytest tests/tui -q" in rendered) == (not has_snapshot and detail == Detail.FULL)


@pytest.mark.parametrize(
    ("status", "exit_code", "theme_key"),
    [
        ("running", None, ThemeKey.WARN),
        ("stopping", None, ThemeKey.WARN),
        ("completed", 0, ThemeKey.METADATA_GREEN_DIM),
        ("completed", 2, ThemeKey.ERROR),
        ("failed", 1, ThemeKey.ERROR),
        ("timed_out", -15, ThemeKey.ERROR),
        ("lost", None, ThemeKey.ERROR),
        ("stopped", -15, ThemeKey.METADATA_DIM),
    ],
)
def test_result_status_has_correct_color_and_exit(status: str, exit_code: int | None, theme_key: ThemeKey) -> None:
    task = _task(status=status, exit_code=exit_code)
    renderable = render_tool_result(_event(ShellTaskUIExtra(action="wait", tasks=[task])), detail=Detail.FULL)
    assert renderable is not None
    console = _console()
    segments = [segment for line in console.render_lines(renderable) for segment in line]
    status_segments = [segment for segment in segments if status in segment.text]
    assert status_segments
    assert all(segment.style == console.get_style(theme_key) for segment in status_segments)
    rendered = _render(renderable)
    if exit_code is not None:
        assert f"exit {exit_code}" in rendered
    assert "✓" not in rendered


def test_full_output_preserves_blank_lines_whitespace_and_literal_markup() -> None:
    ui_extra = ShellTaskUIExtra(
        action="output",
        tasks=[_task()],
        output="\n  [red]literal[/red]\n\n    indented\n",
        next_offset=123,
        truncated=True,
    )
    rendered = _render(render_tool_result(_event(ui_extra), detail=Detail.FULL))
    lines = rendered.splitlines()
    markup_index = next(idx for idx, line in enumerate(lines) if "[red]literal[/red]" in line)
    assert not lines[markup_index - 1].strip()
    assert lines[markup_index].startswith(" " * 14)
    assert not lines[markup_index + 1].strip()
    assert lines[markup_index + 2].startswith(" " * 16)
    assert "next_offset 123 · has_more" in rendered
    console = _console()
    renderable = render_tool_result(_event(ui_extra), detail=Detail.FULL)
    assert renderable is not None
    markup_segments = [
        segment for line in console.render_lines(renderable) for segment in line if "[red]" in segment.text
    ]
    assert markup_segments
    assert all(segment.style == console.get_style(ThemeKey.TOOL_RESULT) for segment in markup_segments)


@pytest.mark.parametrize("action", ["output", "list", "stop"])
@pytest.mark.parametrize("task_status", ["running", "completed", "failed"])
def test_compact_success_hides_result_details(action: str, task_status: str) -> None:
    ui_extra = ShellTaskUIExtra.model_validate(
        {
            "action": action,
            "tasks": [_task(status=task_status, exit_code=2 if task_status == "failed" else 0).model_dump()],
            "output": "command output must stay hidden",
            "next_offset": 123,
            "truncated": True,
        }
    )
    assert render_tool_result(_event(ui_extra), detail=Detail.COMPACT) is None
    rendered = _render(
        render_compact_tool_result(
            tools.MANAGE_SHELL,
            json.dumps({"action": action, "task_id": _TASK_ID}),
            "Model-facing text must not be displayed",
            status="success",
            ui_extra=ui_extra,
        )
    )
    assert "$ Shell" in rendered
    assert "next_offset" not in rendered
    assert "has_more" not in rendered
    assert "exit" not in rendered
    assert "command output" not in rendered
    assert "Model-facing" not in rendered
    assert len(rendered.splitlines()) == 1


@pytest.mark.parametrize("output", ["", "\n", "   "])
def test_empty_and_blank_output_are_distinct(output: str) -> None:
    rendered = _render(
        render_tool_result(
            _event(ShellTaskUIExtra(action="output", tasks=[_task()], output=output)), detail=Detail.FULL
        )
    )
    assert ("(no output)" in rendered) == (output == "")


def test_list_and_output_limits_preserve_late_failures_and_output_tail() -> None:
    detail = Detail.FULL
    tasks = [_task(task_id=f"task-{idx}", description=f"task description {idx}") for idx in range(20)]
    tasks[-2] = _task(
        task_id="failure", description="important failure", status="failed", exit_code=9, reason="bad run"
    )
    rendered = _render(render_tool_result(_event(ShellTaskUIExtra(action="list", tasks=tasks)), detail=detail))
    limit = FULL_TOOL_RESULT_MAX_LINES
    assert rendered.count("task description") == limit - 1
    assert "important failure failure · failed · exit 9 · bad run" in rendered
    assert f"more {20 - limit} tasks" in rendered
    ui_extra = ShellTaskUIExtra(
        action="output", tasks=[tasks[-2]], output="\n".join(f"output-{idx}" for idx in range(20))
    )
    rendered = _render(render_tool_result(_event(ui_extra), detail=detail))
    assert "failed · exit 9 · bad run" in rendered
    assert "output-0" in rendered
    assert "output-19" in rendered
    assert f"more {20 - limit} lines" in rendered


def test_empty_task_list_and_expired_output_are_explained() -> None:
    assert "No managed shell tasks." in _render(
        render_tool_result(_event(ShellTaskUIExtra(action="list", tasks=[])), detail=Detail.FULL)
    )
    rendered = _render(
        render_tool_result(
            _event(ShellTaskUIExtra(action="output", tasks=[_task(status="lost", output_expired=True)])),
            detail=Detail.FULL,
        )
    )
    assert "lost" in rendered
    assert "output expired" in rendered


@pytest.mark.parametrize("legacy_kind", ["snapshot", "list", "output"])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_old_persisted_json_uses_structured_rendering(legacy_kind: str, detail: Detail) -> None:
    task = _task(status="failed", exit_code=7)
    if legacy_kind == "snapshot":
        result = task.model_dump_json()
    elif legacy_kind == "list":
        result = json.dumps([task.model_dump()])
    else:
        result = ShellTaskOutput(task=task, output="  old output", next_offset=22, truncated=True).model_dump_json()
    if detail.is_compact and legacy_kind != "snapshot":
        assert render_tool_result(_event(result=result), detail=detail) is None
        return
    rendered = _render(render_tool_result(_event(result=result), detail=detail))
    expected_identity = legacy_kind == "list" or (legacy_kind == "snapshot" and detail.is_compact)
    assert ("Run targeted tests" in rendered) == expected_identity
    assert "failed · exit 7" in rendered
    assert "output_path" not in rendered
    if legacy_kind == "output":
        assert ("  old output" in rendered) == (detail == Detail.FULL)
        assert "next_offset 22 · has_more" in rendered


@pytest.mark.parametrize("result", ["{broken json", '{"unknown": "data"}', "Output saved to /tmp/output.log"])
def test_unknown_malformed_or_offloaded_content_keeps_fallback(result: str) -> None:
    assert render_tool_result(_event(result=result)) is None
    rendered = _render(render_tool_result(_event(result=result), detail=Detail.FULL))
    assert result in rendered


def test_legacy_json_decode_is_bounded_and_ui_extra_never_decodes_model_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_decode(_result: str) -> object:
        pytest.fail("JSON decoding must not run")

    monkeypatch.setattr("klaude_code.tui.components.tools._manage_shell.json.loads", unexpected_decode)
    ui_extra = ShellTaskUIExtra(action="wait", tasks=[_task()])
    assert extract_shell_task_ui_extra(ui_extra, "{model text}") is ui_extra
    assert extract_shell_task_ui_extra(None, "[" + " " * (2 * 1024 * 1024)) is None


def test_error_uses_existing_fallback_instead_of_snapshot_status() -> None:
    rendered = _render(render_tool_result(_event(result="ManageShell error: task not found", status="error")))
    assert "ManageShell error: task not found" in rendered


@pytest.mark.parametrize("status", ["error", "aborted"])
@pytest.mark.parametrize("with_ui_extra", [False, True])
def test_compact_failure_shows_only_first_reason(status: str, with_ui_extra: bool) -> None:
    event = _event(
        ShellTaskUIExtra(action="output", tasks=[_task()], next_offset=123) if with_ui_extra else None,
        result="\n  task not found\nextra diagnostic details\nmore details",
        status="error" if status == "error" else "aborted",
    )
    rendered = _render(render_tool_result(event))
    assert rendered.strip() == "task not found"
    assert len(rendered.splitlines()) == 1
    if not with_ui_extra:
        full = _render(render_tool_result(event, detail=Detail.FULL))
        assert "extra diagnostic details" in full
        assert "more details" in full


@pytest.mark.parametrize("width", [12, 24, 40])
def test_narrow_cjk_calls_and_results_remain_readable(width: int) -> None:
    task = _task(description="运行测试", status="failed", exit_code=1)
    event = events.ToolCallEvent(
        session_id="main",
        tool_call_id="manage-1",
        tool_name=tools.MANAGE_SHELL,
        arguments=json.dumps({"action": "wait", "task_id": _TASK_ID}),
    )
    call = _render(render_tool_call(event, shell_task=task), width=width)
    result = _render(render_tool_result(_event(ShellTaskUIExtra(action="wait", tasks=[task]))), width=width)
    assert "Shell" in call
    assert "Wait" in call
    assert "运行测试" in result
    assert "failed" in result
    assert "1" in result


@pytest.mark.parametrize("width", [12, 120])
def test_ui_extra_survives_event_serialization_and_compact_result_reuses_renderer(width: int) -> None:
    event = _event(ShellTaskUIExtra(action="wait", tasks=[_task(status="running")]))
    restored = events.ToolResultEvent.model_validate_json(event.model_dump_json())
    assert isinstance(restored.ui_extra, ShellTaskUIExtra)
    assert _render(render_tool_result(restored, detail=Detail.FULL)) == _render(
        render_tool_result(event, detail=Detail.FULL)
    )
    rendered = _render(
        render_compact_tool_result(
            tools.MANAGE_SHELL,
            json.dumps({"action": "wait", "task_id": _TASK_ID}),
            event.result,
            status="success",
            ui_extra=restored.ui_extra,
        ),
        width=width,
    )
    assert "$ Shell" in rendered
    if width == 120:
        assert "Waiting for Run targeted tests" in rendered
    else:
        assert "targeted" in rendered
    assert "running" not in rendered
    assert "✓" not in rendered
    assert "Model-facing" not in rendered
