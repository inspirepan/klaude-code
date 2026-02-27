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


def test_render_ask_user_question_tool_result_does_not_truncate_middle() -> None:
    result = "\n---\n".join(
        [
            "Question: Q1\nAnswer:\n- A\n- B\n- C",
            "Question: Q2\nAnswer:\n- D\n- E\n- F",
            "Question: Q3\nAnswer:\n- G\n- H\n- I",
        ]
    )

    event = events.ToolResultEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.ASK_USER_QUESTION,
        result=result,
        status="success",
        is_last_in_turn=True,
    )

    output = _render_event_to_text(event)

    assert "Question: Q2" in output
    assert "... (more" not in output
    assert "… (more" not in output
