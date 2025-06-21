import os
import re
from typing import Literal, Optional

from rich.abc import RichRenderable
from rich.console import Console, Group, RenderResult
from rich.markup import escape
from rich.panel import Panel
from rich.status import Status
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

light_theme = Theme(
    {
        'orange': 'rgb(201,125,92)',
        'blue': 'rgb(62,99,153)',
        'red': 'rgb(158,57,66)',
        'green': 'rgb(65,120,64)',
        'agent_result': 'rgb(210,231,227)',
        'yellow': 'rgb(143,110,44)',
        'purple': 'rgb(139,134,248)',
        'diff_removed': 'white on rgb(242,172,180)',
        'diff_added': 'white on rgb(133,216,133)',
        'diff_removed_char': 'white on rgb(193,81,78)',
        'diff_added_char': 'white on rgb(80,155,78)',
    }
)

dark_theme = Theme(
    {
        'orange': 'rgb(201,125,92)',
        'blue': 'rgb(62,99,153)',
        'red': 'rgb(237,116,130)',
        'green': 'rgb(65,120,64)',
        'agent_result': 'rgb(10,31,27)',
        'yellow': 'rgb(143,110,44)',
        'purple': 'rgb(139,134,248)',
        'diff_removed': 'white on rgb(242,172,180)',
        'diff_added': 'white on rgb(133,216,133)',
        'diff_removed_char': 'white on rgb(193,81,78)',
        'diff_added_char': 'white on rgb(80,155,78)',
    }
)


class ConsoleProxy:
    def __init__(self):
        # TODO: theme detect or config
        self.console = Console(theme=light_theme)
        self.silent = False

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()


def render_status(status: str, spinner: str = 'bouncingBall', spinner_style: str = 'white'):
    return Status(status, console=console.console, spinner=spinner, spinner_style=spinner_style)


def format_style(content: str | Text, style: Optional[str] = None):
    if style:
        if isinstance(content, Text):
            return content
        return f'[{style}]{content}[/{style}]'
    return content


def render_message(
    message: str | Text,
    *,
    style: Optional[str] = None,
    mark_style: Optional[str] = None,
    mark: Optional[str] = '⏺',
    status: Literal['processing', 'success', 'error', 'canceled'] = 'success',
    mark_width: int = 0,
) -> RichRenderable:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=mark_width, no_wrap=True)
    table.add_column(overflow='fold')
    if status == 'error':
        mark = format_style(mark, 'red')
    elif status == 'canceled':
        mark = format_style(mark, 'yellow')
    elif status == 'processing':
        mark = format_style('○', mark_style)
    else:
        mark = format_style(mark, mark_style)
    table.add_row(mark, format_style(message, style))
    return table


def render_suffix(content: str | RichRenderable, style: Optional[str] = None, render_text: bool = False) -> RichRenderable:
    if not content:
        return ''
    table = Table.grid(padding=(0, 1))
    table.add_column(width=2, no_wrap=True, style=style)
    table.add_column(overflow='fold', style=style)
    table.add_row('  ⎿', Text(escape(content)) if isinstance(content, str) and not render_text else content)
    return table


def render_markdown(text: str) -> str:
    """Convert Markdown syntax to Rich format string"""
    if not text:
        return ''
    text = escape(text)
    # Handle bold: **text** -> [bold]text[/bold]
    text = re.sub(r'\*\*(.*?)\*\*', r'[bold]\1[/bold]', text)

    # Handle italic: *text* -> [italic]text[/italic]
    text = re.sub(r'\*([^*\n]+?)\*', r'[italic]\1[/italic]', text)

    # Handle inline code: `text` -> [purple]text[/purple]
    text = re.sub(r'`([^`\n]+?)`', r'[purple]\1[/purple]', text)

    # Handle inline lists, replace number symbols
    lines = text.split('\n')
    formatted_lines = []

    for line in lines:
        # Handle headers: # text -> [bold]# text[/bold]
        if line.strip().startswith('#'):
            # Keep all # symbols and bold the entire line
            line = f'[bold]{line}[/bold]'
        # Handle blockquotes: > text -> [gray]▌ text[/gray]
        elif line.strip().startswith('>'):
            # Remove > symbol and maintain indentation
            quote_content = re.sub(r'^(\s*)>\s?', r'\1', line)
            line = f'[gray]▌ {quote_content}[/gray]'
        else:
            # Match numbered lists: 1. -> •
            line = re.sub(r'^(\s*)(\d+)\.\s+', r'\1• ', line)
            # Match dash lists: - -> •
            line = re.sub(r'^(\s*)[-*]\s+', r'\1• ', line)
        if line.strip():
            formatted_lines.append(line)

    return '\n'.join(formatted_lines)


def render_hello() -> RenderResult:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=0, no_wrap=True)
    table.add_column(overflow='fold')
    table.add_row(
        '[orange]✻[/orange]',
        Group(
            'Welcome to [bold]Klaude Code[/bold]!',
            '',
            '[italic]/status for your current setup[/italic]',
            '',
            format_style('cwd: {}'.format(os.getcwd()), 'bright_black'),
        ),
    )
    return Group(
        Panel.fit(table, border_style='orange'),
        '',
        render_message(
            'type \\ followed by [bold]Enter[/bold] to insert newlines\ntype / to choose slash command\ntype ! to run bash command\ntype # to write memory\ntype * to plan mode\n',
            mark='※ Tip:',
            style='bright_black',
            mark_style='bright_black',
            mark_width=5,
        ),
        '',
    )


INTERRUPT_TIP = '[gray]Press Ctrl+C to interrupt[/gray]'


def truncate_middle_text(text: str, max_lines: int = 30) -> RichRenderable:
    lines = text.splitlines()

    if len(lines) <= max_lines + 5:
        return text

    head_lines = max_lines // 2
    tail_lines = max_lines - head_lines
    middle_lines = len(lines) - head_lines - tail_lines

    head_content = '\n'.join(lines[:head_lines])
    tail_content = '\n'.join(lines[-tail_lines:])
    return Group(
        head_content,
        Text('···', style='bright_black'),
        Text.assemble('+ ', Text(str(middle_lines), style='bold'), ' lines', style='bright_black'),
        Text('···', style='bright_black'),
        tail_content,
    )
