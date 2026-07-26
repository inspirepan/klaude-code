from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import DiffFileDiff, DiffLine, DiffSpan, DiffUIExtra, MarkdownDocUIExtra
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_apply_patch_tool_call, render_tool_result
from klaude_code.tui.transcript_detail import Detail


def _render(renderable: object) -> str:
    console = Console(width=100, record=True, force_terminal=False, theme=get_theme().app_theme)
    console.print(renderable)
    return console.export_text()


def _file_diff(path: str, line: int) -> DiffFileDiff:
    return DiffFileDiff(
        file_path=path,
        lines=[
            DiffLine(
                kind="add",
                new_line_no=line,
                spans=[DiffSpan(op="insert", text="changed")],
            )
        ],
        stats_add=1,
    )


def test_single_file_patch_shows_path_in_call_and_not_diff() -> None:
    call = render_apply_patch_tool_call('{"patch":"*** Begin Patch\\n*** Update File: src/example.py\\n*** End Patch"}')
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="patch-1",
            tool_name=tools.APPLY_PATCH,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=DiffUIExtra(files=[_file_diff("src/example.py", 3)]),
        )
    )

    assert result is not None
    assert "  ± Patch   ./src/example.py" in _render(call)
    rendered_result = _render(result)
    assert "src/example.py" not in rendered_result
    assert "3 +changed" in rendered_result
    assert rendered_result.startswith("    ╭")
    assert rendered_result.rstrip().endswith("╯")
    assert "└" not in rendered_result


def test_multi_file_patch_shows_count_and_paths_per_diff() -> None:
    call = render_apply_patch_tool_call(
        '{"patch":"*** Begin Patch\\n*** Update File: src/one.py\\n*** Update File: src/two.py\\n*** End Patch"}'
    )
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="patch-1",
            tool_name=tools.APPLY_PATCH,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=DiffUIExtra(
                files=[
                    _file_diff("src/one.py", 3),
                    _file_diff("src/two.py", 8),
                ]
            ),
        )
    )

    assert result is not None
    assert "  ± Patch   2 files" in _render(call)
    rendered_result = _render(result)
    assert "src/one.py (+1)" in rendered_result
    assert "src/two.py (+1)" in rendered_result
    assert rendered_result.startswith("    ╭")
    assert rendered_result.rstrip().endswith("╯")
    assert "└" not in rendered_result


def test_markdown_file_renders_in_file_change_panel_without_background() -> None:
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="write-1",
            tool_name=tools.WRITE,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=MarkdownDocUIExtra(file_path="README.md", content="# Heading"),
        )
    )

    assert result is not None
    console = Console(width=100, record=True, force_terminal=False, theme=get_theme().app_theme)
    segments = list(console.render(result))
    console.print(result)
    rendered = console.export_text()
    assert rendered.startswith("    ╭")
    assert rendered.rstrip().endswith("╯")
    assert "Heading" in rendered
    assert all(segment.style is None or segment.style.bgcolor is None for segment in segments)


def test_compact_mixed_patch_summarizes_delete_and_truncates_add() -> None:
    added_lines = [
        DiffLine(kind="add", new_line_no=line, spans=[DiffSpan(op="equal", text=f"new line {line}")])
        for line in range(1, 8)
    ]
    updated = _file_diff("src/existing.py", 8)
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="patch-mixed",
            tool_name=tools.APPLY_PATCH,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=DiffUIExtra(
                files=[
                    DiffFileDiff(
                        file_path="docs/new.md",
                        lines=added_lines,
                        stats_add=7,
                        change_type="add",
                    ),
                    DiffFileDiff(
                        file_path="docs/obsolete.md",
                        lines=[],
                        stats_remove=345,
                        change_type="delete",
                    ),
                    updated,
                ]
            ),
        ),
        detail=Detail.COMPACT,
    )

    assert result is not None
    rendered = _render(result)
    assert "docs/new.md (+7)" in rendered
    assert "new line 5" in rendered
    assert "new line 6" not in rendered
    assert "(2 added lines hidden)" in rendered
    assert "docs/obsolete.md (-345)" in rendered
    assert "src/existing.py (+1)" in rendered
    assert "changed" in rendered
    assert "Done!" not in rendered


def test_expanded_added_file_patch_shows_all_lines() -> None:
    lines = [
        DiffLine(kind="add", new_line_no=line, spans=[DiffSpan(op="equal", text=f"new line {line}")])
        for line in range(1, 8)
    ]
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="patch-add",
            tool_name=tools.APPLY_PATCH,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=DiffUIExtra(
                files=[
                    DiffFileDiff(
                        file_path="docs/new.md",
                        lines=lines,
                        stats_add=7,
                        change_type="add",
                    )
                ]
            ),
        ),
        detail=Detail.FULL,
    )

    assert result is not None
    rendered = _render(result)
    assert "new line 7" in rendered
    assert "added lines hidden" not in rendered


def test_deleted_empty_file_patch_shows_zero_line_summary() -> None:
    result = render_tool_result(
        events.ToolResultEvent(
            session_id="main",
            tool_call_id="patch-delete-empty",
            tool_name=tools.APPLY_PATCH,
            result="Done!",
            status="success",
            is_last_in_step=True,
            ui_extra=DiffUIExtra(
                files=[
                    DiffFileDiff(
                        file_path="empty.txt",
                        lines=[],
                        stats_remove=0,
                        change_type="delete",
                    )
                ]
            ),
        )
    )

    assert result is not None
    rendered = _render(result)
    assert "empty.txt (-0)" in rendered
    assert "Done!" not in rendered
