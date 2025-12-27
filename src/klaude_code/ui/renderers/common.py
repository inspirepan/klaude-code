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
    # Expand tabs to spaces to ensure correct alignment when Rich applies padding.
    text = text.expandtabs(8)

    if max_lines <= 0:
        truncated_lines = text.split("\n")
        remaining = max(0, len(truncated_lines))
        return Text(f"… (more {remaining} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED)

    lines = text.split("\n")
    truncated_lines = 0
    head_lines: list[str] = []
    tail_lines: list[str] = []

    if len(lines) > max_lines:
        truncated_lines = len(lines) - max_lines

        # If the hidden section is too small, show everything instead of inserting
        # the "(more N lines)" indicator.
        if truncated_lines < 5:
            truncated_lines = 0
            head_lines = lines
        else:
            head_count = max_lines // 2
            tail_count = max_lines - head_count
            head_lines = lines[:head_count]
            tail_lines = lines[-tail_count:]
    else:
        head_lines = lines

    def append_line(out: Text, line: str) -> None:
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

    out = Text()
    if base_style is not None:
        out.style = base_style

    for idx, line in enumerate(head_lines):
        append_line(out, line)
        if idx < len(head_lines) - 1 or truncated_lines > 0 or tail_lines:
            out.append("\n")

    if truncated_lines > 0:
        out.append_text(Text(f"⋮ (more {truncated_lines} lines)\n", style=ThemeKey.TOOL_RESULT_TRUNCATED))

    for idx, line in enumerate(tail_lines):
        append_line(out, line)
        if idx < len(tail_lines) - 1:
            out.append("\n")

    return out
