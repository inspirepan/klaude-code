from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_tool_result


def _render_event_to_text(event: events.ToolResultEvent) -> str:
    console = Console(width=100, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def test_web_search_truncation_indicator_uses_tool_name_indent() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.WEB_SEARCH,
        result=result,
        status="success",
        is_last_in_turn=True,
    )

    output = _render_event_to_text(event)

    assert "│            … (more 6 lines)" in output


def test_bash_truncation_indicator_keeps_existing_padding() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.BASH,
        result=result,
        status="success",
        is_last_in_turn=True,
    )

    output = _render_event_to_text(event)

    assert "│      … (more 6 lines)" in output


def test_edit_diff_result_uses_tool_name_indent_in_tree_wrap() -> None:
    from klaude_code.protocol import model

    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.EDIT,
        result="",
        status="success",
        is_last_in_turn=True,
        ui_extra=model.DiffUIExtra(
            files=[
                model.DiffFileDiff(
                    file_path="demo.txt",
                    lines=[
                        model.DiffLine(
                            kind="add",
                            new_line_no=1,
                            spans=[model.DiffSpan(op="insert", text="alpha")],
                        )
                    ],
                    stats_add=1,
                )
            ]
        ),
    )

    output = _render_event_to_text(event)
    line = output.splitlines()[0]

    assert line.startswith("└ ")
    assert line[2:7] == "     "
    assert line.endswith("1 +alpha")


def test_web_search_indent_shrinks_on_narrow_width() -> None:
    result = "\n".join(f"line-{idx}" for idx in range(12))
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.WEB_SEARCH,
        result=result,
        status="success",
        is_last_in_turn=True,
    )

    console = Console(width=14, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event)
    assert renderable is not None
    console.print(renderable)
    output = console.export_text()

    assert "lin" in output
