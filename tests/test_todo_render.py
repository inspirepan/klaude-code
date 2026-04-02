import json

from rich.console import Console

from klaude_code.protocol import events, model, tools
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_tool_call, render_tool_result


def _render_tool_call_to_text(event: events.ToolCallEvent) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_call(event)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def _render_tool_result_to_text(event: events.ToolResultEvent) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_result(event)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def test_render_todo_write_tool_call_hides_explanation_details() -> None:
    explanation = "Scope all references before deleting auth code."
    event = events.ToolCallEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.TODO_WRITE,
        arguments=json.dumps(
            {
                "todos": [{"content": "Locate OAuth references", "status": "in_progress"}],
                "explanation": explanation,
            }
        ),
    )

    output = _render_tool_call_to_text(event)

    assert "◈" in output
    assert "Update To-Dos" in output
    assert explanation not in output


def test_render_todo_result_keeps_explanation_once() -> None:
    explanation = "Scope all references before deleting auth code."
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
                explanation=explanation,
            )
        ),
        is_last_in_turn=True,
    )

    output = _render_tool_result_to_text(event)

    assert todo_content in output
    assert output.count(explanation) == 1
    assert output.index(explanation) < output.index(todo_content)
