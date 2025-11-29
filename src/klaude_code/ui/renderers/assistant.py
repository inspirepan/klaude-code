from rich.console import RenderableType

from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.markdown import NoInsetMarkdown


def render_assistant_message(content: str, *, code_theme: str) -> RenderableType | None:
    """Render assistant message for replay history display.

    Returns None if content is empty.
    """
    stripped = content.strip()
    if len(stripped) == 0:
        return None

    grid = create_grid()
    grid.add_row(
        "•",
        NoInsetMarkdown(stripped, code_theme=code_theme),
    )
    return grid
