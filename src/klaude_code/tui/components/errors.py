from rich.console import RenderableType
from rich.text import Text

from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey


def render_error(error_msg: Text, *, can_retry: bool = False) -> RenderableType:
    """Render error with X mark for error events."""
    grid = create_grid()
    message_style = ThemeKey.WARN if can_retry else ThemeKey.ERROR
    mark_style = ThemeKey.WARN_BOLD if can_retry else ThemeKey.ERROR_BOLD

    error_msg.style = message_style
    error_msg.overflow = "fold"
    grid.add_row(Text("✘", style=mark_style), error_msg)

    return grid


def render_tool_error(error_msg: Text) -> RenderableType:
    """Render error with indent for tool results."""
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    error_msg.overflow = "fold"
    grid.add_row(Text(" "), error_msg)
    return grid
