from rich.console import RenderableType
from rich.text import Text

from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey


def render_error(error_msg: Text) -> RenderableType:
    """Render error with X mark for error events."""
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    grid.add_row(Text("✘", style=ThemeKey.ERROR_BOLD), error_msg)
    return grid


def render_tool_error(error_msg: Text) -> RenderableType:
    """Render error with indent for tool results."""
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    grid.add_row(Text(" "), error_msg)
    return grid
