from rich.console import RenderableType
from rich.text import Text

from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey


def render_error(error_msg: Text, indent: int = 2) -> RenderableType:
    """Stateless error renderer.

    Shows a two-column grid with an error mark and truncated message.
    """
    grid = create_grid()
    error_msg.style = ThemeKey.ERROR
    grid.add_row(Text(" " * indent + "✘", style=ThemeKey.ERROR_BOLD), error_msg)
    return grid
