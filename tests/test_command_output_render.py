from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui.components.command_output import render_command_output
from klaude_code.tui.components.rich.theme import ThemeKey


def test_render_command_output_default_uses_command_output_style() -> None:
    event = events.CommandOutputEvent(session_id="s1", command_name="test", content="hello")

    rendered = render_command_output(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "hello"
    assert rendered.style == ThemeKey.COMMAND_OUTPUT


def test_render_command_output_default_error_uses_error_style() -> None:
    event = events.CommandOutputEvent(session_id="s1", command_name="test", content="oops", is_error=True)

    rendered = render_command_output(event)

    assert isinstance(rendered, Text)
    assert rendered.plain == "oops"
    assert rendered.style == ThemeKey.ERROR
