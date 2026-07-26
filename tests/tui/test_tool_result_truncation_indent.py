import pytest
from rich.console import Console

from klaude_code.const import DIFF_MAX_RENDER_WIDTH
from klaude_code.protocol import events, tools
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffSpan, DiffUIExtra
from klaude_code.tui.components.diffs import render_structured_diff
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import FULL_TOOL_RESULT_MAX_LINES, render_tool_result
from klaude_code.tui.transcript_detail import Detail


def _render_event_to_text(event: events.ToolResultEvent, *, detail: Detail = Detail.COMPACT, width: int = 100) -> str:
    console = Console(width=width, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event, detail=detail)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def test_web_search_truncation_indicator_uses_result_padding() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.WEB_SEARCH,
        result=result,
        status="success",
        is_last_in_step=True,
    )

    output = _render_event_to_text(event)

    assert "  … (more 6 lines)" in output


def test_bash_truncation_indicator_uses_result_padding() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.BASH,
        result=result,
        status="success",
        is_last_in_step=True,
    )

    output = _render_event_to_text(event)

    assert "  … (more 6 lines)" in output


def test_full_bash_result_keeps_all_lines_and_wraps_long_content() -> None:
    result = "\n".join(
        [*(f"line-{idx}" for idx in range(FULL_TOOL_RESULT_MAX_LINES - 1)), f"tail-{'x' * 80}-END"]
    )
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.BASH,
        result=result,
        status="success",
    )

    output = _render_event_to_text(event, detail=Detail.FULL, width=40)

    assert "line-0" in output
    assert f"line-{FULL_TOOL_RESULT_MAX_LINES - 2}" in output
    assert "END" in output
    assert "more" not in output


def test_full_bash_result_keeps_configured_lines_with_head_and_tail() -> None:
    total_lines = FULL_TOOL_RESULT_MAX_LINES + 10
    head_count = FULL_TOOL_RESULT_MAX_LINES // 2
    tail_start = total_lines - (FULL_TOOL_RESULT_MAX_LINES - head_count)
    result = "\n".join(f"line-{idx}" for idx in range(total_lines))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.BASH,
        result=result,
        status="success",
    )

    output = _render_event_to_text(event, detail=Detail.FULL)

    assert "line-0" in output
    assert f"line-{head_count - 1}" in output
    assert f"line-{head_count}" not in output
    assert f"line-{tail_start - 1}" not in output
    assert f"line-{tail_start}" in output
    assert f"line-{total_lines - 1}" in output
    assert "… (more 10 lines)" in output


@pytest.mark.parametrize("tool_name", [tools.EDIT, tools.WRITE])
def test_file_diff_result_renders_in_panel(tool_name: str) -> None:
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tool_name,
        result="",
        status="success",
        is_last_in_step=True,
        ui_extra=DiffUIExtra(
            files=[
                DiffFileDiff(
                    file_path="demo.txt",
                    lines=[
                        DiffLine(
                            kind="add",
                            new_line_no=1,
                            spans=[DiffSpan(op="insert", text="alpha")],
                        )
                    ],
                    stats_add=1,
                )
            ]
        ),
    )

    output = _render_event_to_text(event, width=DIFF_MAX_RENDER_WIDTH + 30)
    lines = output.splitlines()

    assert lines[0].startswith("    ╭")
    assert lines[-1].startswith("    ╰")
    assert "1 +alpha" in lines[1]
    assert len(lines[1].lstrip()) == DIFF_MAX_RENDER_WIDTH + 4


def test_edit_diff_result_shows_old_line_number_for_remove() -> None:
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.EDIT,
        result="",
        status="success",
        is_last_in_step=True,
        ui_extra=DiffUIExtra(
            files=[
                DiffFileDiff(
                    file_path="demo.txt",
                    lines=[
                        DiffLine(
                            kind="remove",
                            old_line_no=7,
                            spans=[DiffSpan(op="delete", text="alpha")],
                        )
                    ],
                    stats_remove=1,
                )
            ]
        ),
    )

    output = _render_event_to_text(event)

    assert "7 -alpha" in output.splitlines()[1]


def test_structured_diff_highlight_width_is_capped() -> None:
    ui_extra = DiffUIExtra(
        files=[
            DiffFileDiff(
                file_path="demo.txt",
                lines=[
                    DiffLine(
                        kind="add",
                        new_line_no=1,
                        spans=[DiffSpan(op="insert", text="alpha")],
                    )
                ],
                stats_add=1,
            )
        ]
    )

    console = Console(width=DIFF_MAX_RENDER_WIDTH + 20, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_structured_diff(ui_extra))
    output = console.export_text()

    assert len(output.splitlines()[0]) == DIFF_MAX_RENDER_WIDTH


def test_structured_diff_wraps_to_narrow_width() -> None:
    ui_extra = DiffUIExtra(
        files=[
            DiffFileDiff(
                file_path="demo.txt",
                lines=[
                    DiffLine(
                        kind="add",
                        new_line_no=1,
                        spans=[
                            DiffSpan(
                                op="insert",
                                text="alpha beta gamma delta epsilon zeta eta theta iota kappa",
                            )
                        ],
                    )
                ],
                stats_add=1,
            )
        ]
    )

    console = Console(width=40, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_structured_diff(ui_extra))
    output = console.export_text()

    lines = output.splitlines()
    assert len(lines) > 1
    assert all(len(line) == 40 for line in lines)
    assert "kappa" in output


def test_structured_diff_truncates_context_line_with_ellipsis() -> None:
    ui_extra = DiffUIExtra(
        files=[
            DiffFileDiff(
                file_path="demo.txt",
                lines=[
                    DiffLine(
                        kind="ctx",
                        old_line_no=1,
                        new_line_no=1,
                        spans=[
                            DiffSpan(
                                op="equal",
                                text="alpha beta gamma delta epsilon zeta eta theta iota kappa",
                            )
                        ],
                    )
                ],
            )
        ]
    )

    console = Console(width=40, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_structured_diff(ui_extra))
    output = console.export_text()

    lines = output.splitlines()
    assert len(lines) == 1
    assert len(lines[0]) == 40
    assert lines[0].endswith("…")


def test_structured_diff_keeps_large_line_number_prefix() -> None:
    ui_extra = DiffUIExtra(
        files=[
            DiffFileDiff(
                file_path="demo.txt",
                lines=[
                    DiffLine(
                        kind="remove",
                        old_line_no=10000,
                        spans=[DiffSpan(op="delete", text="alpha")],
                    )
                ],
                stats_remove=1,
            )
        ]
    )

    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(render_structured_diff(ui_extra))
    output = console.export_text()

    assert output.splitlines()[0].rstrip().endswith("10000 -alpha")


def test_web_search_indent_shrinks_on_narrow_width() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.WEB_SEARCH,
        result=result,
        status="success",
        is_last_in_step=True,
    )

    console = Console(width=14, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event)
    assert renderable is not None
    console.print(renderable)
    output = console.export_text()

    assert "lin" in output
