import re
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from rich import box
from rich.abc import RichRenderable
from rich.console import Group, RenderResult
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from ..utils.str_utils import normalize_tabs
from .colors import ColorStyle


def render_message(
    message: str | RichRenderable,
    *,
    style: Optional[str] = None,
    mark_style: Optional[str] = None,
    mark: Optional[str] = '⏺',
    status: Literal['processing', 'success', 'error', 'canceled'] = 'success',
    mark_width: int = 0,
    render_text: bool = False,
) -> RichRenderable:
    table = Table.grid(padding=(0, 1))
    table.add_column(width=mark_width, no_wrap=True)
    table.add_column(overflow='fold')
    if status == 'error':
        mark = Text(mark, style=ColorStyle.ERROR)
    elif status == 'canceled':
        mark = Text(mark, style=ColorStyle.WARNING)
    elif status == 'processing':
        mark = Text('○', style=mark_style)
    else:
        mark = Text(mark, style=mark_style)
    if isinstance(message, str):
        if render_text:
            render_message = Text.from_markup(message, style=style)
        else:
            render_message = Text(message, style=style)
    else:
        render_message = message

    table.add_row(mark, render_message)
    return table


def render_grid(item: List[List[Union[str, RichRenderable]]], padding: Tuple[int, int] = (0, 1)) -> RichRenderable:
    if not item:
        return ''
    column_count = len(item[0])
    grid = Table.grid(padding=padding, expand=True)
    for _ in range(column_count):
        grid.add_column(overflow='fold')
    for row in item:
        grid.add_row(*row)
    return grid


def render_suffix(content: str | RichRenderable, style: Optional[str] = None, render_text: bool = False) -> RichRenderable:
    if not content:
        return ''
    table = Table.grid(padding=(0, 1))
    table.add_column(width=3, no_wrap=True, style=style)
    table.add_column(overflow='fold', style=style)
    table.add_row('  ⎿ ', Text(content, style=style) if isinstance(content, str) and not render_text else content)
    return table


def render_markdown(text: str, style: Optional[Union[str, Style]] = None) -> Group:
    """Convert Markdown syntax to Rich Group"""
    if not text:
        return Group()
    text = escape(text)
    # Handle bold: **text** -> [bold]text[/bold]
    text = re.sub(r'\*\*(.*?)\*\*', r'[bold]\1[/bold]', text)

    # Handle italic: *text* -> [italic]text[/italic]
    text = re.sub(r'\*([^*\n]+?)\*', r'[italic]\1[/italic]', text)

    # Handle strikethrough: ~~text~~ -> [strike]text[/strike]
    text = re.sub(r'~~(.*?)~~', r'[strike]\1[/strike]', text)

    # Handle inline code: `text` -> [inline_code]text[/inline_code]
    text = re.sub(r'`([^`\n]+?)`', r'[inline_code]\1[/inline_code]', text)

    lines = text.split('\n')
    formatted_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        line = normalize_tabs(line)

        # Check for table start
        if line.strip().startswith('|') and line.strip().endswith('|'):
            # Look ahead for header separator or another table row
            if i + 1 < len(lines):
                next_line = lines[i + 1].strip()
                # Check if next line is separator or another table row
                if re.match(r'^\s*\|[\s\-\|:]+\|\s*$', next_line) or (next_line.startswith('|') and next_line.endswith('|')):
                    table = _parse_markdown_table(lines, i, style=style)
                    formatted_lines.append(table['table'])
                    i = table['end_index']
                    continue

        # Handle other line types
        if line.strip().startswith('##'):
            stripped = line.strip()
            # Match any number of # followed by space and title text
            header_match = re.match(r'^(#+)\s+(.+)', stripped)
            if header_match:
                hashes, title = header_match.groups()
                line = Text.from_markup(f'{hashes} [bold]{title}[/bold]', style=style if len(hashes) > 2 else ColorStyle.H2)
            else:
                line = Text.from_markup(line, style=style + Style(bold=True))
        elif line.strip().startswith('>'):
            quote_content = re.sub(r'^(\s*)>\s?', r'\1', line)
            line = Text.from_markup(f'[muted]▌ {quote_content}[/muted]', style=style)
        elif line.strip() == '---':
            line = Rule(style=ColorStyle.SEPARATOR)
        else:
            # Handle list items with proper indentation
            list_match = re.match(r'^(\s*)([*\-+]|\d+\.)\s+(.+)', line)
            if list_match:
                indent, marker, content = list_match.groups()
                # Create a grid with proper indentation
                table = Table.grid(padding=(0, 0))
                table.add_column(width=len(indent) + len(marker) + 1, no_wrap=True)
                table.add_column(overflow='fold')
                marker_text = Text.from_markup(f'{indent}{marker} ', style=style)
                content_text = Text.from_markup(content, style=style)
                table.add_row(marker_text, content_text)
                line = table
            else:
                line = Text.from_markup(line, style=style)

        formatted_lines.append(line)
        i += 1

    return Group(*formatted_lines)


def _parse_markdown_table(lines: list[str], start_index: int, style: Optional[Union[str, Style]] = None) -> dict:
    """Parse markdown table and return rich Table"""
    header_line = lines[start_index].strip()
    # Extract headers
    headers = [Text(cell.strip(), style=style) for cell in header_line.split('|')[1:-1]]

    # Create table
    table = Table(show_header=True, header_style='bold', box=box.SQUARE, show_lines=True, style=style)
    for header in headers:
        table.add_column(header)

    # Check if next line is separator
    i = start_index + 1
    if i < len(lines) and re.match(r'^\s*\|[\s\-\|:]+\|\s*$', lines[i].strip()):
        # Skip separator line
        i += 1

    # Parse data rows
    while i < len(lines) and lines[i].strip().startswith('|') and lines[i].strip().endswith('|'):
        row_data = [cell.strip() for cell in lines[i].split('|')[1:-1]]
        # Pad row if it has fewer columns than headers
        while len(row_data) < len(headers):
            row_data.append('')
        table.add_row(*row_data[: len(headers)], style=style)
        i += 1

    return {'table': table, 'end_index': i}


def build_hello_tips() -> List[str]:
    basic_tips = [
        'type \\ followed by [main]Enter[/main] to insert newlines',
        'type / to choose slash command',
        'type ! to run bash command',
        'type # to memorize',
        'type * to start plan mode',
        'type @ to mention a file',
    ]
    tips = []

    if (Path.cwd() / '.klaude' / 'sessions').exists():
        import random

        tips.append(random.choice(basic_tips))
        tips.append('run [main]klaude --continue[/main] or [main]klaude --resume[/main] to resume a conversation')
    else:
        tips.extend(basic_tips)
    if not (Path.cwd() / 'CLAUDE.md').exists():
        tips.append('run [main]/init[/main] to analyse your codebase')
    if (Path.cwd() / '.klaude' / 'mcp.json').exists():
        tips.append('run [main]klaude --mcp[/main] or [main]/mcp[/main] to enable MCP tools')

    return tips


def render_hello() -> RenderResult:
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
    table = render_grid(grid_data)

    return Group(
        Panel.fit(table, border_style=ColorStyle.CLAUDE),
        '',
        render_message(
            '\n'.join(build_hello_tips()),
            mark='※ Tips:',
            style=ColorStyle.MUTED,
            mark_style=ColorStyle.MUTED,
            mark_width=6,
            render_text=True,
        ),
        '',
    )


def truncate_middle_text(text: str, max_lines: int = 50) -> RichRenderable:
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
        Text('···', style=ColorStyle.MUTED),
        Text.assemble('+ ', Text(str(middle_lines), style='bold'), ' lines', style=ColorStyle.MUTED),
        Text('···', style=ColorStyle.MUTED),
        tail_content,
    )
