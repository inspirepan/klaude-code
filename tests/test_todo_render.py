import json

from rich.console import Console

from klaude_code.protocol import events, model, tools
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_tool_call, render_tool_result


def _render_tool_call_to_text(event: events.ToolCallEvent) -> str | None:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_call(event)
    if renderable is None:
        return None
    console.print(renderable)
    return console.export_text()


def _render_tool_result_to_text(event: events.ToolResultEvent) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def test_render_todo_write_tool_call_is_not_rendered() -> None:
    event = events.ToolCallEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.TODO_WRITE,
        arguments=json.dumps(
            {
                "todos": [{"content": "Locate OAuth references", "status": "in_progress"}],
            }
        ),
    )

    output = _render_tool_call_to_text(event)

    assert output is None


def test_render_todo_result_only_shows_todos() -> None:
    todo_content = "Locate OAuth references"
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.TODO_WRITE,
        result="Done",
        status="success",
        ui_extra=model.TodoListUIExtra(
            todo_list=model.TodoUIExtra(
                todos=[model.TodoItem(content=todo_content, status="in_progress")],
                new_completed=[],
            )
        ),
        is_last_in_turn=True,
    )

    output = _render_tool_result_to_text(event)

    assert "Update To-Dos" in output
    assert todo_content in output
    assert "└" not in output
    assert "╭" in output
    assert "│  ◉" in output


def test_render_todo_error_result_keeps_update_todos_context() -> None:
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.TODO_WRITE,
        result="invalid todos payload",
        status="error",
        is_last_in_turn=True,
    )

    output = _render_tool_result_to_text(event)

    assert "Update To-Dos" in output
    assert "invalid todos payload" in output
    assert "└" not in output


def test_render_bash_tool_result_adds_left_padding() -> None:
    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.BASH,
        result="hi",
        status="success",
        is_last_in_turn=True,
    )

    output = _render_tool_result_to_text(event)

    assert output.rstrip("\n").rstrip() == "└      hi"
