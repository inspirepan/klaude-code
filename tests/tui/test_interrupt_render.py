import io

from pytest import MonkeyPatch
from rich.console import Console
from rich.style import Style
from rich.text import Text

from klaude_code.protocol import events, tools
from klaude_code.tui import renderer as renderer_module
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.components.tools import render_generic_tool_result
from klaude_code.tui.components.user_input import render_interrupt
from klaude_code.tui.renderer import TUICommandRenderer


def test_interrupt_theme_uses_warn_color() -> None:
    console = Console(theme=get_theme().app_theme)

    assert console.get_style(ThemeKey.INTERRUPT) == console.get_style(ThemeKey.WARN)


def test_render_interrupt_and_aborted_tool_result_use_interrupt_style() -> None:
    interrupt = render_interrupt()
    aborted = render_generic_tool_result("cancelled", status="aborted")
    error = render_generic_tool_result("failed", status="error")

    assert isinstance(interrupt, Text)
    assert interrupt.style == ThemeKey.INTERRUPT
    assert isinstance(aborted, Text)
    assert aborted.style == ThemeKey.INTERRUPT
    assert isinstance(error, Text)
    assert error.style == ThemeKey.ERROR


def test_renderer_uses_interrupt_style_for_aborted_sub_agent_tool_result(monkeypatch: MonkeyPatch) -> None:
    renderer = TUICommandRenderer()
    output = io.StringIO()
    renderer.console = Console(file=output, theme=renderer.themes.app_theme, width=100, force_terminal=False)
    renderer.console.push_theme(renderer.themes.markdown_theme)

    seen: dict[str, str | Style] = {}

    def _fake_render_tool_error(error_msg: Text, *, style: str | Style = ThemeKey.ERROR) -> Text:
        seen["style"] = style
        return Text(error_msg.plain, style=style)

    monkeypatch.setattr(renderer_module.c_errors, "render_tool_error", _fake_render_tool_error)

    event = events.ToolResultEvent(
        session_id="sub-1",
        tool_call_id="tc-1",
        tool_name=tools.BASH,
        result="[Request interrupted by user for tool use]",
        status="aborted",
    )

    assert renderer.display_tool_call_result(event, is_sub_agent=True) is True
    assert seen["style"] == ThemeKey.INTERRUPT
