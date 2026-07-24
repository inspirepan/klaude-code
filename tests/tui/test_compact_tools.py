import asyncio
import io
import json
from pathlib import Path
from typing import Literal

import pytest
from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import BashUIExtra, ReadPreviewLine, ReadPreviewUIExtra
from klaude_code.tui.commands import (
    AppendBashCommandOutput,
    FlushOpenBlocks,
    RenderBashCommandEnd,
    RenderCommand,
    RenderCompactToolResult,
    RenderToolCall,
    RenderToolResult,
)
from klaude_code.tui.components.bash_syntax import summarize_bash_command
from klaude_code.tui.components.tools.compact import render_compact_tool_activity, render_compact_tool_result
from klaude_code.tui.renderer import TUICommandRenderer


def _renderer_and_output() -> tuple[TUICommandRenderer, io.StringIO]:
    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    return renderer, output


def _bash_commands(
    *,
    arguments: str,
    result: str,
    status: Literal["success", "error", "aborted"] = "success",
    exit_code: int | None = None,
    compact: bool = True,
) -> list[RenderCommand]:
    call = events.ToolCallEvent(
        session_id="main",
        tool_call_id="bash-1",
        tool_name=tools.BASH,
        arguments=arguments,
    )
    result_event = events.ToolResultEvent(
        session_id="main",
        tool_call_id=call.tool_call_id,
        tool_name=tools.BASH,
        result=result,
        status=status,
        ui_extra=BashUIExtra(exit_code=exit_code) if exit_code is not None else None,
    )
    if compact:
        return [RenderCompactToolResult(event=result_event, arguments=arguments), FlushOpenBlocks()]
    return [RenderToolCall(event=call), RenderToolResult(event=result_event, is_sub_agent_session=False)]


def test_compact_bash_prefers_description_and_hides_command_output() -> None:
    renderer, output = _renderer_and_output()

    asyncio.run(
        renderer.execute(
            _bash_commands(
                arguments='{"command":"jj status && jj diff --git","description":"确认提交后工作区为空"}',
                result="The working copy has no changes.\nmore output",
            )
        )
    )

    rendered = output.getvalue()
    assert rendered == "$ Bash 确认提交后工作区为空  jj status · jj diff ✓\n\n"
    assert "jj status &&" not in rendered
    assert "working copy" not in rendered


def test_compact_bash_command_summary_is_not_bold() -> None:
    renderer, _ = _renderer_and_output()
    renderable = render_compact_tool_result(
        tools.BASH,
        '{"command":"git status && git diff","description":"检查工作区"}',
        "clean",
        status="success",
        exit_code=0,
    )

    segments = [segment for line in renderer.console.render_lines(renderable) for segment in line]
    command_segments = [segment for segment in segments if "git status · git diff" in segment.text]
    assert command_segments
    assert all(segment.style is None or not segment.style.bold for segment in command_segments)


def test_compact_bash_falls_back_to_flattened_command() -> None:
    renderer, output = _renderer_and_output()
    arguments = json.dumps({"command": "uv run pytest tests/tui \\" + "\n  -q"})

    asyncio.run(
        renderer.execute(
            _bash_commands(
                arguments=arguments,
                result="passed",
            )
        )
    )

    assert output.getvalue() == "$ Bash uv run pytest tests/tui ✓\n\n"


def test_compact_bash_failure_keeps_first_error_line() -> None:
    renderer, output = _renderer_and_output()

    asyncio.run(
        renderer.execute(
            _bash_commands(
                arguments='{"command":"uv run pytest","description":"运行测试"}',
                result="[stdout]\nfailed test details",
                exit_code=1,
            )
        )
    )

    rendered = output.getvalue()
    assert rendered == "$ Bash 运行测试  uv run pytest ✗ · Command exited with code 1\n\n"
    assert "failed test details" not in rendered


def test_expanded_bash_keeps_command_and_output() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_compact_transcript(False)

    asyncio.run(
        renderer.execute(
            _bash_commands(
                arguments='{"command":"echo full","description":"显示完整命令"}',
                result="full output",
                compact=False,
            )
        )
    )

    rendered = output.getvalue()
    assert "echo full" in rendered
    assert "full output" in rendered
    assert "# 显示完整命令" not in rendered


def test_compact_bash_live_tail_is_transient() -> None:
    stream_updates: list[tuple[tuple[str, ...], bool]] = []
    renderer = TUICommandRenderer(stream_sink=lambda lines, end: stream_updates.append((lines, end)))
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)
    commands = _bash_commands(
        arguments='{"command":"long command","description":"运行长命令"}',
        result="live output\ndone",
    )
    commands[0:0] = [
        AppendBashCommandOutput(events.BashCommandOutputDeltaEvent(session_id="main", content="live output\n")),
        RenderBashCommandEnd(events.BashCommandEndEvent(session_id="main")),
    ]

    asyncio.run(renderer.execute(commands))

    assert any(lines == ("       live output",) and not end for lines, end in stream_updates)
    assert stream_updates[-1] == ((), True)
    assert output.getvalue() == "$ Bash 运行长命令  long ✓\n\n"


def test_compact_bash_results_in_same_step_have_no_blank_line_between_them() -> None:
    renderer, output = _renderer_and_output()
    first = _bash_commands(arguments='{"command":"pwd","description":"查看目录"}', result="/tmp")[0]
    second = _bash_commands(arguments='{"command":"jj status","description":"检查状态"}', result="clean")[0]

    asyncio.run(renderer.execute([first, second, FlushOpenBlocks()]))

    assert output.getvalue() == "$ Bash 查看目录  pwd ✓\n$ Bash 检查状态  jj status ✓\n\n"


def test_compact_activity_clamps_description_to_forty_characters() -> None:
    description = "x" * 50

    rendered = render_compact_tool_activity(
        tools.BASH,
        f'{{"command":"echo hi","description":"{description}"}}',
    )

    assert rendered.plain == f"Bash {'x' * 39}…"


def test_bash_command_summary_keeps_auditable_scope() -> None:
    assert summarize_bash_command("pwd") == "pwd"
    assert summarize_bash_command("rg -n 'needle' src/klaude_code tests -g '*.py'") == "rg src/klaude_code tests"
    assert summarize_bash_command("rg --files web/src | head -n 20") == "rg web/src"
    assert summarize_bash_command("jj status && jj diff --git") == "jj status · jj diff"


def test_bash_command_summary_falls_back_for_unsafe_shell_syntax() -> None:
    assert summarize_bash_command("echo $(pwd)") == "echo $(pwd)"
    assert summarize_bash_command("rg needle src > matches.txt") == "rg needle src > matches.txt"


def test_bash_command_summary_shortens_paths_under_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = tmp_path / "ai-gateway"
    project.mkdir()
    monkeypatch.chdir(project)
    target = project / "worker/src/durable-objects/user-balance.ts"

    assert summarize_bash_command(f"rg -n groupBy {target}") == "rg worker/src/durable-objects/user-balance.ts"


def test_compact_read_hides_offset_preview_but_keeps_call() -> None:
    renderer, output = _renderer_and_output()
    call = events.ToolCallEvent(
        session_id="main",
        tool_call_id="read-1",
        tool_name=tools.READ,
        arguments='{"file_path":"README.md","offset":10,"limit":3}',
    )
    result = events.ToolResultEvent(
        session_id="main",
        tool_call_id=call.tool_call_id,
        tool_name=tools.READ,
        result="line 10\nline 11\nline 12",
        status="success",
        ui_extra=ReadPreviewUIExtra(
            lines=[ReadPreviewLine(line_no=10, content="line 10")],
            remaining_lines=2,
        ),
    )

    asyncio.run(
        renderer.execute(
            [
                RenderToolCall(event=call),
                RenderToolResult(event=result, is_sub_agent_session=False),
                FlushOpenBlocks(),
            ]
        )
    )

    rendered = output.getvalue()
    assert "→ Read ./README.md 10:12" in rendered
    assert "line 10" not in rendered


def test_expanded_read_keeps_offset_preview() -> None:
    renderer, output = _renderer_and_output()
    renderer.set_compact_transcript(False)
    call = events.ToolCallEvent(
        session_id="main",
        tool_call_id="read-1",
        tool_name=tools.READ,
        arguments='{"file_path":"README.md","offset":10,"limit":1}',
    )
    result = events.ToolResultEvent(
        session_id="main",
        tool_call_id=call.tool_call_id,
        tool_name=tools.READ,
        result="line 10",
        status="success",
        ui_extra=ReadPreviewUIExtra(lines=[ReadPreviewLine(line_no=10, content="line 10")], remaining_lines=0),
    )

    asyncio.run(
        renderer.execute([RenderToolCall(event=call), RenderToolResult(event=result, is_sub_agent_session=False)])
    )

    assert "line 10" in output.getvalue()
