from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code import const
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey

# UI markers
ASSISTANT_MESSAGE_MARK = "•"


def render_assistant_message(content: str, *, code_theme: str) -> RenderableType | None:
    """Render assistant message for replay history display.

    Returns None if content is empty.
    """
    stripped = content.strip()
    if len(stripped) == 0:
        return None

    grid = create_grid()
    grid.add_row(
        Text(ASSISTANT_MESSAGE_MARK, style=ThemeKey.ASSISTANT_MESSAGE_MARK),
        Padding(NoInsetMarkdown(stripped, code_theme=code_theme), (0, const.MARKDOWN_RIGHT_MARGIN, 0, 0)),
    )
    return grid
