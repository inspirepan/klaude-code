from __future__ import annotations

import pytest

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import (
    DiffFileDiff,
    DiffLine,
    DiffSpan,
    DiffUIExtra,
    MarkdownDocUIExtra,
    MultiUIExtra,
    SubAgentState,
)
from klaude_code.tui.commands import SubAgentSummary
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail


def _diff() -> DiffUIExtra:
    return DiffUIExtra(
        files=[
            DiffFileDiff(
                file_path="src/demo.py",
                lines=[
                    DiffLine(
                        kind="add",
                        new_line_no=1,
                        spans=[DiffSpan(op="insert", text="new_value = 1")],
                    )
                ],
                stats_add=1,
            )
        ]
    )


def _diffs_expanded() -> TranscriptDetail:
    # ctrl-t in compact mode: sub-agent changes show their diffs again.
    detail = TranscriptDetail(Detail.COMPACT)
    detail.toggle_diffs()
    return detail


def _sub_agent_state() -> SubAgentState:
    return SubAgentState(
        sub_agent_type="general-purpose",
        sub_agent_desc="update generated files",
        sub_agent_prompt="prompt",
    )


def _renderer_with_child(detail: TranscriptDetail | None = None) -> TUICommandRenderer:
    renderer = TUICommandRenderer(detail=detail)
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    return renderer


def _change(tool_name: str, call_id: str, ui_extra: DiffUIExtra | MultiUIExtra) -> events.ToolResultEvent:
    return events.ToolResultEvent(
        session_id="child", tool_call_id=call_id, tool_name=tool_name, result="ok", status="success", ui_extra=ui_extra
    )


def _finish(renderer: TUICommandRenderer, result_summary: str = "updated the files") -> str:
    with renderer.bulk_render_capture() as output:
        renderer.display_sub_agent_batch_summary(
            (
                SubAgentSummary(
                    session_id="child",
                    title="GeneralPurpose",
                    description="update generated files",
                    status="success",
                    model_id="test-model",
                    duration_s=3.0,
                    tool_count=2,
                    token_count=None,
                    result_summary=result_summary,
                ),
            )
        )
    return output.getvalue()


def _record(renderer: TUICommandRenderer, *changes: events.ToolResultEvent) -> str:
    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        for change in changes:
            assert renderer.display_tool_call_result(change, is_sub_agent=True) is False
    return output.getvalue()


def test_compact_sub_agent_edits_print_nothing_and_sum_up_in_the_run_block() -> None:
    renderer = _renderer_with_child()
    doc = MarkdownDocUIExtra(file_path="docs/new.md", content="# Title\nbody")
    printed = _record(
        renderer,
        _change(tools.EDIT, "edit-1", _diff()),
        _change(tools.APPLY_PATCH, "patch-1", MultiUIExtra(items=[_diff(), doc])),
    )
    assert printed == ""

    block = _finish(renderer)
    assert "GeneralPurpose: update generated files ✓" in block
    assert "↳ updated the files" in block
    assert "± 2 files  +4  ./src/demo.py, ./docs/new.md" in block
    assert "new_value = 1" not in block and "╭" not in block
    # The next run of the same agent reports only its own changes.
    assert "± " not in _finish(renderer)


def test_ctrl_t_shows_each_sub_agent_diff_under_its_run_block() -> None:
    detail = TranscriptDetail(Detail.COMPACT)
    detail.toggle_diffs()
    renderer = _renderer_with_child(detail)
    _record(renderer, _change(tools.EDIT, "edit-1", _diff()))

    block = _finish(renderer)
    assert "± 1 file  +1  ./src/demo.py" in block
    assert "new_value = 1" in block and "╭" in block


def test_run_block_without_a_result_has_no_placeholder_line() -> None:
    block = _finish(_renderer_with_child(), result_summary="")
    assert "GeneralPurpose: update generated files ✓" in block
    assert "↳" not in block and "no summary" not in block


@pytest.mark.parametrize("tool_name", [tools.WRITE, tools.APPLY_PATCH])
def test_compact_markdown_preview_shows_fifteen_source_lines_and_remaining_count(tool_name: str) -> None:
    renderer = TUICommandRenderer()
    content = "\n".join(f"Line {line}" for line in range(1, 18))
    markdown = MarkdownDocUIExtra(file_path="docs/new.md", content=content)
    event = events.ToolResultEvent(
        session_id="main",
        tool_call_id="markdown-1",
        tool_name=tool_name,
        result="created",
        status="success",
        ui_extra=MultiUIExtra(items=[markdown]) if tool_name == tools.APPLY_PATCH else markdown,
    )

    with renderer.bulk_render_capture() as output:
        rendered = renderer.display_tool_call_result(event)

    assert rendered is True
    plain = output.getvalue()
    assert not plain.startswith("\n")
    assert "Line 15" in plain
    assert "Line 16" not in plain
    assert "Line 17" not in plain
    assert "docs/new.md" not in plain
    assert "… 2 more lines · ctrl-t" in plain


def test_compact_markdown_preview_preserves_source_lines_and_uses_ellipsis() -> None:
    renderer = TUICommandRenderer()
    long_line = f"first line {'x' * 200} END"
    event = events.ToolResultEvent(
        session_id="main",
        tool_call_id="write-markdown-1",
        tool_name=tools.WRITE,
        result="created",
        status="success",
        ui_extra=MarkdownDocUIExtra(
            file_path=f"docs/{'nested/' * 20}new.md",
            content=f"{long_line}\nsecond line\nthird line",
        ),
    )

    with renderer.bulk_render_capture() as output:
        renderer.display_tool_call_result(event)

    plain = output.getvalue()
    assert "first line" in plain
    assert "END" not in plain
    assert "second line" in plain
    assert "first line second line" not in plain
    assert "…" in plain


@pytest.mark.parametrize("tool_name", [tools.WRITE, tools.APPLY_PATCH])
def test_expanded_markdown_preview_keeps_all_lines(tool_name: str) -> None:
    renderer = TUICommandRenderer()
    renderer.set_transcript_detail(Detail.FULL)
    content = "\n".join(f"# Line {line}" for line in range(1, 8))
    markdown = MarkdownDocUIExtra(file_path="docs/new.md", content=content)
    event = events.ToolResultEvent(
        session_id="main",
        tool_call_id="markdown-1",
        tool_name=tool_name,
        result="created",
        status="success",
        ui_extra=MultiUIExtra(items=[markdown]) if tool_name == tools.APPLY_PATCH else markdown,
    )

    with renderer.bulk_render_capture() as output:
        rendered = renderer.display_tool_call_result(event)

    assert rendered is True
    plain = output.getvalue()
    assert "Line 7" in plain
    assert "more 2 lines" not in plain
