from rich.console import RenderableType
from rich.text import Text

from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.renderers.common import create_grid


def render_error(error_msg: Text, indent: int = 2) -> RenderableType:
    """Stateless error renderer.

    Shows a two-column grid with an error mark and truncated message.
    """
    grid = create_grid()
    error_msg.stylize(ThemeKey.ERROR)
    grid.add_row(Text(" " * indent + "✘", style=ThemeKey.ERROR_BOLD), error_msg)
    return grid
