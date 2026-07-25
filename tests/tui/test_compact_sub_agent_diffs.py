from __future__ import annotations

import pytest
from rich.console import Group
from rich.style import Style
from rich.text import Text

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
from klaude_code.tui.components import sub_agent as c_sub_agent
from klaude_code.tui.components import tools as c_tools
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail


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


def _sub_agent_state() -> SubAgentState:
    return SubAgentState(
        sub_agent_type="general-purpose",
        sub_agent_desc="update generated files",
        sub_agent_prompt="prompt",
    )


@pytest.mark.parametrize(
    ("tool_name", "action"),
    [
        (tools.EDIT, "Edit"),
        (tools.WRITE, "Write"),
        (tools.APPLY_PATCH, "Patch"),
    ],
)
def test_compact_sub_agent_file_tools_render_identity_and_full_diff(tool_name: str, action: str) -> None:
    renderer = TUICommandRenderer()
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="change-1",
        tool_name=tool_name,
        result="updated",
        status="success",
        ui_extra=_diff(),
    )

    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        rendered = renderer.display_tool_call_result(event, is_sub_agent=True)

    assert rendered is True
    plain = output.getvalue()
    assert f"GeneralPurpose: update generated files · {action}" in plain
    assert "src/demo.py (+1)" in plain
    assert plain.count("src/demo.py") == 1
    assert "new_value = 1" in plain
    assert "╭" in plain
    assert "╰" in plain


def test_compact_sub_agent_file_action_does_not_bold_path() -> None:
    renderer = TUICommandRenderer()
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="edit-1",
        tool_name=tools.EDIT,
        result="updated",
        status="success",
        ui_extra=_diff(),
    )

    action = c_tools.render_compact_file_change_action(event, "Edit")
    segments = [segment for segment in renderer.console.render(action) if segment.text]
    tool_segment = next(segment for segment in segments if "Edit" in segment.text)
    path_segment = next(segment for segment in segments if "src/demo.py" in segment.text)

    assert tool_segment.style is not None and tool_segment.style.bold is True
    assert path_segment.style is None or path_segment.style.bold is not True


def test_compact_sub_agent_replay_write_keeps_markdown_preview_and_diff() -> None:
    renderer = TUICommandRenderer()
    renderer.set_replay_mode(True)
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="write-1",
        tool_name=tools.WRITE,
        result="updated",
        status="success",
        ui_extra=MultiUIExtra(
            items=[
                MarkdownDocUIExtra(file_path="src/demo.md", content="markdown preview should stay hidden"),
                _diff(),
            ]
        ),
    )

    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        rendered = renderer.display_tool_call_result(event, is_sub_agent=True)

    assert rendered is True
    plain = output.getvalue()
    assert "new_value = 1" in plain
    assert "markdown preview should stay hidden" in plain
    assert plain.count("╭") == 2
    assert plain.count("╰") == 2


def test_compact_sub_agent_multi_file_patch_keeps_paths_with_each_change() -> None:
    renderer = TUICommandRenderer()
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="patch-1",
        tool_name=tools.APPLY_PATCH,
        result="updated",
        status="success",
        ui_extra=MultiUIExtra(
            items=[
                MarkdownDocUIExtra(file_path="docs/first.md", content="first"),
                MarkdownDocUIExtra(file_path="docs/second.md", content="second"),
                _diff(),
            ]
        ),
    )

    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        rendered = renderer.display_tool_call_result(event, is_sub_agent=True)

    assert rendered is True
    plain = output.getvalue()
    assert "GeneralPurpose: update generated files · Patch · 3 files" in plain
    assert plain.count("docs/first.md") == 1
    assert plain.count("docs/second.md") == 1
    assert plain.count("src/demo.py") == 1


@pytest.mark.parametrize(
    ("tool_name", "action"),
    [
        (tools.WRITE, "Write"),
        (tools.APPLY_PATCH, "Patch"),
    ],
)
def test_compact_sub_agent_new_markdown_renders_document_without_diff(tool_name: str, action: str) -> None:
    renderer = TUICommandRenderer()
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    markdown = MarkdownDocUIExtra(file_path="docs/new.md", content="# New document\n\nMarkdown body")
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="markdown-1",
        tool_name=tool_name,
        result="created",
        status="success",
        ui_extra=MultiUIExtra(items=[markdown]) if tool_name == tools.APPLY_PATCH else markdown,
    )

    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        rendered = renderer.display_tool_call_result(event, is_sub_agent=True)

    assert rendered is True
    plain = output.getvalue()
    assert f"GeneralPurpose: update generated files · {action}" in plain
    assert "docs/new.md" in plain
    assert plain.count("docs/new.md") == 1
    assert "New document" in plain
    assert "Markdown body" in plain


@pytest.mark.parametrize("tool_name", [tools.WRITE, tools.APPLY_PATCH])
def test_compact_markdown_preview_shows_five_source_lines_and_remaining_count(tool_name: str) -> None:
    renderer = TUICommandRenderer()
    content = "\n".join(f"Line {line}" for line in range(1, 8))
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
    assert "Line 5" in plain
    assert "Line 6" not in plain
    assert "Line 7" not in plain
    assert "docs/new.md" not in plain
    assert "… (more 2 lines)" in plain


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


def test_compact_sub_agent_file_change_description_is_italic() -> None:
    rendered = c_sub_agent.render_compact_file_change(
        sub_agent_state=_sub_agent_state(),
        action=Text("Edit", style=ThemeKey.TOOL_NAME),
        change=Text("diff"),
        color=Style(color="green"),
    )

    assert isinstance(rendered, Group)
    header = rendered.renderables[0]
    assert isinstance(header, Text)
    assert any(
        span.style == Style(color="green", italic=True)
        and header.plain[span.start : span.end] == "update generated files"
        for span in header.spans
    )
    assert any(
        span.style == ThemeKey.TOOL_NAME and header.plain[span.start : span.end] == "Edit" for span in header.spans
    )
