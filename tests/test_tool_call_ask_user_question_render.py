import json

from rich.console import Console

from klaude_code.protocol import events, tools
from klaude_code.tui.components.rich.theme import get_theme
from klaude_code.tui.components.tools import render_tool_call


def _render_event_to_text(event: events.ToolCallEvent) -> str:
    console = Console(width=120, record=True, force_terminal=False, theme=get_theme().app_theme)
    renderable = render_tool_call(event)
    assert renderable is not None
    console.print(renderable)
    return console.export_text()


def test_render_ask_user_question_tool_call_shows_marker_and_name_only() -> None:
    event = events.ToolCallEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.ASK_USER_QUESTION,
        arguments=json.dumps(
            {
                "questions": [
                    {"question": "Q1", "header": "Language", "options": [], "multiSelect": False},
                    {"question": "Q2", "header": "Scope", "options": [], "multiSelect": True},
                ]
            }
        ),
    )

    output = _render_event_to_text(event)
    assert "◉" in output
    assert "Agent has 2 questions for you" in output
    assert "Language" not in output
    assert "Scope" not in output


def test_render_ask_user_question_tool_call_ignores_argument_details() -> None:
    event = events.ToolCallEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.ASK_USER_QUESTION,
        arguments=json.dumps(
            {
                "questions": [
                    {"question": "Q1", "options": [], "multiSelect": False},
                    {"question": "Q2", "options": [], "multiSelect": True},
                ]
            }
        ),
    )

    output = _render_event_to_text(event)
    assert "Agent has 2 questions for you" in output
    assert "2 question(s)" not in output


def test_render_ask_user_question_tool_call_singular_text() -> None:
    event = events.ToolCallEvent(
        session_id="s1",
        tool_call_id="tc1",
        tool_name=tools.ASK_USER_QUESTION,
        arguments=json.dumps(
            {
                "questions": [
                    {"question": "Q1", "header": "Language", "options": [], "multiSelect": False},
                ]
            }
        ),
    )

    output = _render_event_to_text(event)
    assert "Agent has a question for you" in output
