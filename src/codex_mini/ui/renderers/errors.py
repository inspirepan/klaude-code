from rich.console import RenderableType
from rich.text import Text

from codex_mini.ui.renderers.common import create_grid, truncate_display
from codex_mini.ui.theme import ThemeKey


def render_error(error_msg: str) -> RenderableType:
    """Stateless error renderer.

    Shows a two-column grid with an error mark and truncated message.
    """
    grid = create_grid()
    grid.add_row(Text("  ✘", style=ThemeKey.ERROR_BOLD), Text(truncate_display(error_msg), style=ThemeKey.ERROR))
    return grid
