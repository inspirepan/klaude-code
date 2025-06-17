import os
import re
from typing import Literal, Optional

from rich import box
from rich.abc import RichRenderable
from rich.columns import Columns
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.layout import Layout
from rich.live import Live
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

light_theme = Theme(
    {
        "orange": "rgb(201,125,92)",
        "blue": "rgb(62,99,153)",
        "gray": "rgb(137,136,131)",
        "red": "rgb(158,57,66)",
        "black": "white",
        "green": "rgb(65,120,64)",
        "purple": "rgb(139,134,248)",
        "diff_removed": "black on rgb(242,172,180)",
        "diff_added": "black on rgb(133,216,133)",
        "diff_removed_char": "black on rgb(193,81,78)",
        "diff_added_char": "black on rgb(80,155,78)",
    }
)

dark_theme = Theme(
    {
        "orange": "rgb(201,125,92)",
        "blue": "rgb(62,99,153)",
        "gray": "rgb(137,136,131)",
        "red": "rgb(237,116,130)",
        "black": "black",
        "green": "rgb(65,120,64)",
        "purple": "rgb(139,134,248)",
        "diff_removed": "black on rgb(242,172,180)",
        "diff_added": "black on rgb(133,216,133)",
        "diff_removed_char": "black on rgb(193,81,78)",
        "diff_added_char": "black on rgb(80,155,78)",
    }
)


class ConsoleProxy:
    def __init__(self):
        self.console = Console(theme=light_theme)  # TODO: theme detect or config
        self.silent = False

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()


def format_style(content: str | Text, style: Optional[str] = None):
    if style:
        if isinstance(content, Text):
            return content.stylize(style)
        return f"[{style}]{content}[/{style}]"
    return content


def render_message(
    message: str | Text,
    *,
    style: Optional[str] = None,
    mark_style: Optional[str] = None,
    mark: Optional[str] = "⏺",
    status: Literal["processing", "success", "error"] = "success",
    mark_width: int = 0,
) -> RichRenderable:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=mark_width, no_wrap=True)
    table.add_column(overflow="fold")
    if status == "error":
        mark = format_style(mark, "red")
    elif status == "processing":
        mark = format_style("○", mark_style)
    else:
        mark = format_style(mark, mark_style)
    table.add_row(mark, format_style(message or "<empty>", style))
    return table


def render_suffix(content: str | RichRenderable, error: bool = False) -> RichRenderable:
    if not content:
        return ""
    table = Table.grid(padding=(0, 1))
    table.add_column(width=2, no_wrap=True, style="red" if error else None)
    table.add_column(overflow="fold", style="red" if error else None)
    table.add_row("  ⎿", Text(escape(content)) if isinstance(content, str) else content)
    return table


def render_markdown(text: str) -> str:
    """Convert Markdown syntax to Rich format string"""
    if not text:
        return ""
    text = escape(text)
    # Handle bold: **text** -> [bold]text[/bold]
    text = re.sub(r"\*\*(.*?)\*\*", r"[bold]\1[/bold]", text)

    # Handle italic: *text* -> [italic]text[/italic]
    text = re.sub(r"\*([^*\n]+?)\*", r"[italic]\1[/italic]", text)

    # Handle inline code: `text` -> [purple]text[/purple]
    text = re.sub(r"`([^`\n]+?)`", r"[purple]\1[/purple]", text)

    # Handle inline lists, replace number symbols
    lines = text.split("\n")
    formatted_lines = []

    for line in lines:
        # Handle headers: # text -> [bold]# text[/bold]
        if line.strip().startswith("#"):
            # Keep all # symbols and bold the entire line
            line = f"[bold]{line}[/bold]"
        # Handle blockquotes: > text -> [gray]▌ text[/gray]
        elif line.strip().startswith(">"):
            # Remove > symbol and maintain indentation
            quote_content = re.sub(r"^(\s*)>\s?", r"\1", line)
            line = f"[gray]▌ {quote_content}[/gray]"
        else:
            # Match numbered lists: 1. -> •
            line = re.sub(r"^(\s*)(\d+)\.\s+", r"\1• ", line)
            # Match dash lists: - -> •
            line = re.sub(r"^(\s*)[-*]\s+", r"\1• ", line)
        formatted_lines.append(line)

    return "\n".join(formatted_lines)


def render_hello() -> RenderResult:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=0, no_wrap=True)
    table.add_column(overflow="fold")
    table.add_row(
        "[orange]✻[/orange]",
        Group(
            "Welcome to [bold]Klaude Code[/bold]!",
            "",
            "[gray][italic]/status for your current setup[/italic][/gray]",
            "",
            format_style("cwd: {}".format(os.getcwd()), "gray"),
        ),
    )
    return Group(
        Panel.fit(table, border_style="orange"),
        "",
        render_message("type \\ followed by [bold]Enter[/bold] to insert newlines\n"
                       "type / to choose slash command\n"
                       "type ! to run bash command\n"
                       "type # to write memory\n"
                       "type * to plan mode\n",
                       mark="※ Tip:", style="gray", mark_style="gray", mark_width=5),
        "",
    )
