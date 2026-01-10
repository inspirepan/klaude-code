from rich.console import RenderableType
from rich.text import Text

from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey


def render_error(error_msg: Text) -> RenderableType:
    """Render error with X mark for error events."""
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    error_msg.overflow = "ellipsis"
    error_msg.no_wrap = True
    grid.add_row(Text("✘", style=ThemeKey.ERROR_BOLD), error_msg)
    return grid


def render_tool_error(error_msg: Text) -> RenderableType:
    """Render error with indent for tool results."""
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    error_msg.overflow = "ellipsis"
    error_msg.no_wrap = True
    grid.add_row(Text(" "), error_msg)
    return grid
