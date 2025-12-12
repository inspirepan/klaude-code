from rich.style import Style
from rich.table import Table
from rich.text import Text

from klaude_code import const
from klaude_code.ui.rich.theme import ThemeKey


def create_grid() -> Table:
    grid = Table.grid(padding=(0, 1))
    grid.add_column(no_wrap=True)
    grid.add_column(overflow="fold")
    return grid


def truncate_display(
    text: str,
    max_lines: int = const.TRUNCATE_DISPLAY_MAX_LINES,
    max_line_length: int = const.TRUNCATE_DISPLAY_MAX_LINE_LENGTH,
    *,
    base_style: str | Style | None = None,
) -> Text:
    """Truncate long text for terminal display.

    Applies `ThemeKey.TOOL_RESULT_TRUNCATED` style to truncation indicators.
    """

    if max_lines <= 0:
        truncated_lines = text.split("\n")
        remaining = max(0, len(truncated_lines))
        return Text(f"… (more {remaining} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED)

    lines = text.split("\n")
    extra_lines = 0
    if len(lines) > max_lines:
        extra_lines = len(lines) - max_lines
        lines = lines[:max_lines]

    out = Text()
    if base_style is not None:
        out.style = base_style

    for idx, line in enumerate(lines):
        if len(line) > max_line_length:
            extra_chars = len(line) - max_line_length
            out.append(line[:max_line_length])
            out.append_text(
                Text(
                    f" … (more {extra_chars} characters in this line)",
                    style=ThemeKey.TOOL_RESULT_TRUNCATED,
                )
            )
        else:
            out.append(line)

        if idx != len(lines) - 1 or extra_lines > 0:
            out.append("\n")

    if extra_lines > 0:
        out.append_text(Text(f"… (more {extra_lines} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED))

    return out
