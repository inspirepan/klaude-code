from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui.components.command_output import render_notice
from klaude_code.tui.components.rich.theme import ThemeKey


def test_render_command_output_default_uses_command_output_style() -> None:
    event = events.NoticeEvent(session_id="s1", content="hello")

    rendered = render_notice(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "hello"
    assert rendered.style == ThemeKey.COMMAND_OUTPUT


def test_render_command_output_default_error_uses_error_style() -> None:
    event = events.NoticeEvent(session_id="s1", content="oops", is_error=True)

    rendered = render_notice(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "oops"
    assert rendered.style == ThemeKey.ERROR
