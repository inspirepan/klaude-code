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
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.renderer import TUICommandRenderer


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
    assert "new_value = 1" in plain


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


def test_compact_sub_agent_new_markdown_write_renders_document_without_diff() -> None:
    renderer = TUICommandRenderer()
    renderer.display_task_start(
        events.TaskStartEvent(session_id="child", model_id="test-model", sub_agent_state=_sub_agent_state())
    )
    event = events.ToolResultEvent(
        session_id="child",
        tool_call_id="write-markdown-1",
        tool_name=tools.WRITE,
        result="created",
        status="success",
        ui_extra=MarkdownDocUIExtra(file_path="docs/new.md", content="# New document\n\nMarkdown body"),
    )

    with renderer.bulk_render_capture() as output, renderer.session_print_context("child"):
        rendered = renderer.display_tool_call_result(event, is_sub_agent=True)

    assert rendered is True
    plain = output.getvalue()
    assert "GeneralPurpose: update generated files · Write" in plain
    assert "New document" in plain
    assert "Markdown body" in plain


def test_compact_sub_agent_file_change_description_is_italic() -> None:
    rendered = c_sub_agent.render_compact_file_change(
        sub_agent_state=_sub_agent_state(),
        action="Edit",
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
