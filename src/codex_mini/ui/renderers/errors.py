from rich.console import RenderableType
from rich.text import Text

from codex_mini.ui.renderers.common import create_grid
from codex_mini.ui.theme import ThemeKey


def render_error(error_msg: Text) -> RenderableType:
    """Stateless error renderer.

    Shows a two-column grid with an error mark and truncated message.
    """
    grid = create_grid()
    error_msg.stylize(ThemeKey.ERROR)
    grid.add_row(Text("  ✘", style=ThemeKey.ERROR_BOLD), error_msg)
    return grid
