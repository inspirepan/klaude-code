from rich.console import RenderableType
from rich.text import Text

from klaude_code.tui.components.common import create_grid, truncate_head, truncate_middle_lines
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.transcript_detail import Detail


def render_error(error_msg: Text, *, can_retry: bool = False) -> RenderableType:
    """Render error with X mark for error events."""
    grid = create_grid()
    message_style = ThemeKey.WARN if can_retry else ThemeKey.ERROR
    mark_style = ThemeKey.WARN_BOLD if can_retry else ThemeKey.ERROR_BOLD

    error_msg.style = message_style
    error_msg.overflow = "fold"
    grid.add_row(Text("✘", style=mark_style), error_msg)
    return grid


def render_tool_error(
    error_msg: str | Text,
    *,
    style: str = ThemeKey.ERROR,
    detail: Detail = Detail.COMPACT,
    max_lines: int | None = None,
) -> RenderableType:
    """Render error with indent for tool results."""
    grid = create_grid()
    message = error_msg.plain if isinstance(error_msg, Text) else error_msg
    if detail.is_compact:
        rendered = truncate_head(message)
    elif max_lines is not None:
        rendered = truncate_middle_lines(message, max_lines=max_lines)
    else:
        rendered = Text(message)
    rendered.style = style
    rendered.overflow = "fold"
    grid.add_row(Text(" "), rendered)
    return grid
