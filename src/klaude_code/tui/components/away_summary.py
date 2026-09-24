from rich.console import RenderableType
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey

RECAP_MARK = "※"
RECAP_LABEL = "Recap"


def render_away_summary(e: events.AwaySummaryEvent) -> RenderableType:
    """Render a 'while you were away' recap as a two-column grid:
    ※ | Recap  <text, wrapped under itself>
    """
    body = Text.assemble(
        (RECAP_LABEL, ThemeKey.RECAP_LABEL),
        ("  ", ""),
        (e.text.strip(), ThemeKey.RECAP_TEXT),
    )
    grid = create_grid()
    grid.add_row(Text(RECAP_MARK, style=ThemeKey.RECAP_MARK), body)
    return grid
