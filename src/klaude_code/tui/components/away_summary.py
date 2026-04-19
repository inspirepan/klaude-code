from rich.console import RenderableType
from rich.text import Text

from klaude_code.protocol import events
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey

RECAP_MARK = "※"

def render_away_summary(e: events.AwaySummaryEvent) -> RenderableType:
    """Render a 'while you were away' recap as a two-column grid:
    ※ | recap: <text>
    """
    grid = create_grid()
    grid.add_row(
        Text(RECAP_MARK, style=ThemeKey.ATTACHMENT),
        Text.assemble(
            ("recap: ", ThemeKey.RECAP_LABEL),
            (e.text, ThemeKey.RECAP_TEXT),
        ),
    )
    return grid
