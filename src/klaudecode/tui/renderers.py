from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from rich.abc import RichRenderable
from rich.console import Group, RenderResult
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .colors import ColorStyle
from .logo import generate_box_drawing_text


def render_message(
    message: str | RichRenderable,
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
        mark = Text(mark, style=ColorStyle.ERROR)
    elif status == 'canceled':
        mark = Text(mark, style=ColorStyle.ERROR)
    elif status == 'processing':
        mark = Text('○', style=mark_style)
    else:
        mark = Text(mark, style=mark_style)
    if isinstance(message, str):
        render_message = Text(message, style=style)
    else:
        render_message = message

    table.add_row(mark, render_message)
    return table


def render_grid(item: List[List[Union[str, RichRenderable]]], padding: Tuple[int, int] = (0, 1)) -> RichRenderable:
    if not item:
        return ''
    column_count = len(item[0])
    grid = Table.grid(padding=padding)
    for _ in range(column_count):
        grid.add_column(overflow='fold')
    for row in item:
        grid.add_row(*row)
    return grid


def render_suffix(content: str | RichRenderable, style: Optional[str] = None) -> RichRenderable:
    if not content:
        return ''
    table = Table.grid(padding=(0, 1))
    table.add_column(width=3, no_wrap=True, style=style)
    table.add_column(overflow='fold', style=style)
    table.add_row('  ⎿ ', Text(content, style=style) if isinstance(content, str) else content)
    return table


def render_hello(show_info: bool = True) -> RenderResult:
    if show_info:
        grid_data = [
            [
                Text('✻', style=ColorStyle.CLAUDE),
                Group(
                    'Welcome to [bold]Klaude Code[/bold]!',
                    '',
                    '[italic]/status for your current setup[/italic]',
                    '',
                    Text('cwd: {}'.format(Path.cwd())),
                ),
            ]
        ]
    else:
        grid_data = [
            [
                Text('✻', style=ColorStyle.CLAUDE),
                Group(
                    'Welcome to [bold]Klaude Code[/bold]!',
                ),
            ]
        ]
    table = render_grid(grid_data)
    return Panel.fit(table, border_style=ColorStyle.CLAUDE)


def get_tip(all_tips: bool = False) -> RichRenderable:
    tips = [
        'Type \\ followed by [main]Enter[/main] to insert newlines',
        'Type / to choose slash command',
        'Type ! to run bash command',
        "Want Claude to remember something? Hit # to add preferences, tools, and instructions to Claude's memory",
        'Type * to start plan mode',
        'Type @ to mention a file',
    ]

    if (Path.cwd() / '.klaude' / 'sessions').exists():
        tips.append('Run [main]klaude --continue[/main] or [main]klaude --resume[/main] to resume a conversation')
    if not (Path.cwd() / 'CLAUDE.md').exists():
        tips.append('Run [main]/init[/main] to analyse your codebase')
    if (Path.cwd() / '.klaude' / 'mcp.json').exists():
        tips.append('Run [main]klaude --mcp[/main] or [main]/mcp[/main] to enable MCP tools')

    if all_tips:
        return Group(*(Text.from_markup(tip, style=ColorStyle.HINT) for tip in tips))

    import random

    return Text.from_markup(random.choice(tips), style=ColorStyle.HINT)


def render_tips() -> RenderResult:
    return render_message(
        get_tip(),
        mark='※ Tip:',
        style=ColorStyle.HINT,
        mark_style=ColorStyle.HINT,
        mark_width=5,
    )


def truncate_middle_text(text: str, max_lines: int = 50, buffer_threshold: int = 20) -> RichRenderable:
    lines = text.splitlines()

    if len(lines) <= max_lines + buffer_threshold:
        return text

    head_lines = max_lines // 2
    tail_lines = max_lines - head_lines
    middle_lines = len(lines) - head_lines - tail_lines

    head_content = '\n'.join(lines[:head_lines])
    tail_content = '\n'.join(lines[-tail_lines:])
    return Group(
        head_content,
        Rule(style=ColorStyle.LINE, title='···'),
        '',
        Text.assemble('+ ', Text(str(middle_lines), style=ColorStyle.MAIN.bold), ' lines', style=ColorStyle.HINT, justify='center'),
        '',
        Rule(style=ColorStyle.LINE, title='···'),
        tail_content,
    )


def render_logo(text: str, color_style: Optional[Union[ColorStyle, str, Style]] = None) -> RichRenderable:
    """
    Render ASCII art logo with optional color style.

    Args:
        text: Text to render as ASCII art
        color_style: ColorStyle enum value, style string, or Rich Style object

    Returns:
        Rich renderable object (Group) with styled ASCII art
    """
    # Generate ASCII art lines
    lines = generate_box_drawing_text(text)

    # Create Text objects for each line with appropriate style
    text_lines = []
    for line in lines:
        if color_style:
            if isinstance(color_style, ColorStyle):
                # Use ColorStyle enum value
                text_lines.append(Text(line, style=color_style.value))
            else:
                # Use string style name or Style object directly
                text_lines.append(Text(line, style=color_style))
        else:
            # No style specified
            text_lines.append(Text(line))

    # Return as Group to handle multiple lines properly
    return Padding.indent(Group(*text_lines), 1)
