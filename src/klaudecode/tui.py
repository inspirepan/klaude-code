import re
import sys
from enum import Enum
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from rich import box
from rich.abc import RichRenderable
from rich.console import Console, Group, RenderableType, RenderResult
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.style import Style
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

from .utils.str_utils import normalize_tabs


class ColorStyle(str, Enum):
    # AI and user interaction
    AI_MESSAGE = 'ai_message'
    AI_THINKING = 'ai_thinking'
    # For status indicators
    ERROR = 'error'
    SUCCESS = 'success'
    WARNING = 'warning'
    INFO = 'info'
    HIGHLIGHT = 'highlight'
    MAIN = 'main'
    MUTED = 'muted'
    SEPARATOR = 'separator'
    TODO_COMPLETED = 'todo_completed'
    TODO_IN_PROGRESS = 'todo_in_progress'
    # Tools and agents
    AGENT_BORDER = 'agent_border'
    # Code
    DIFF_REMOVED_LINE = 'diff_removed_line'
    DIFF_ADDED_LINE = 'diff_added_line'
    DIFF_REMOVED_CHAR = 'diff_removed_char'
    DIFF_ADDED_CHAR = 'diff_added_char'
    CONTEXT_LINE = 'context_line'
    INLINE_CODE = 'inline_code'
    # Prompt toolkit colors
    INPUT_PLACEHOLDER = 'input_placeholder'
    COMPLETION_MENU = 'completion_menu'
    COMPLETION_SELECTED_FG = 'completion_selected_fg'
    COMPLETION_SELECTED_BG = 'completion_selected_bg'
    # Input mode colors
    BASH_MODE = 'bash_mode'
    MEMORY_MODE = 'memory_mode'
    PLAN_MODE = 'plan_mode'
    # Markdown
    H2 = 'h1'

    def bold(self) -> Style:
        return console.console.get_style(self.value) + Style(bold=True)

    def italic(self) -> Style:
        return console.console.get_style(self.value) + Style(italic=True)

    def bold_italic(self) -> Style:
        return console.console.get_style(self.value) + Style(bold=True, italic=True)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return self.value


light_theme = Theme(
    {
        # AI and user interaction
        ColorStyle.AI_MESSAGE: 'rgb(181,105,72)',
        ColorStyle.AI_THINKING: 'rgb(62,99,153)',
        # Status indicators
        ColorStyle.ERROR: 'rgb(158,57,66)',
        ColorStyle.SUCCESS: 'rgb(65,120,64)',
        ColorStyle.WARNING: 'rgb(143,110,44)',
        ColorStyle.INFO: 'rgb(62,99,153)',
        ColorStyle.HIGHLIGHT: 'rgb(0,3,3)',
        ColorStyle.MAIN: 'rgb(102,102,102)',
        ColorStyle.MUTED: 'rgb(136,139,139)',
        ColorStyle.SEPARATOR: 'rgb(200,200,200)',
        # Todo
        ColorStyle.TODO_COMPLETED: 'rgb(65,120,64)',
        ColorStyle.TODO_IN_PROGRESS: 'rgb(62,99,153)',
        # Tools and agents
        ColorStyle.AGENT_BORDER: 'rgb(205,232,227)',
        # Code
        ColorStyle.DIFF_REMOVED_LINE: 'rgb(0,0,0) on rgb(255,168,180)',
        ColorStyle.DIFF_ADDED_LINE: 'rgb(0,0,0) on rgb(105,219,124)',
        ColorStyle.DIFF_REMOVED_CHAR: 'rgb(0,0,0) on rgb(239,109,119)',
        ColorStyle.DIFF_ADDED_CHAR: 'rgb(0,0,0) on rgb(57,177,78)',
        ColorStyle.CONTEXT_LINE: 'rgb(0,0,0)',
        ColorStyle.INLINE_CODE: 'rgb(109,104,218)',
        # Prompt toolkit
        ColorStyle.INPUT_PLACEHOLDER: 'rgb(136,139,139)',
        ColorStyle.COMPLETION_MENU: 'rgb(154,154,154)',
        ColorStyle.COMPLETION_SELECTED_FG: 'rgb(74,74,74)',
        ColorStyle.COMPLETION_SELECTED_BG: 'rgb(170,221,255)',
        # Input mode colors
        ColorStyle.BASH_MODE: 'rgb(234,51,134)',
        ColorStyle.MEMORY_MODE: 'rgb(109,104,218)',
        ColorStyle.PLAN_MODE: 'rgb(43,100,101)',
        # Markdown
        ColorStyle.H2: 'rgb(181,75,52)',
    }
)

dark_theme = Theme(
    {
        # AI and user interaction
        ColorStyle.AI_MESSAGE: 'rgb(201,125,92)',
        ColorStyle.AI_THINKING: 'rgb(180,204,245)',
        # Status indicators
        ColorStyle.ERROR: 'rgb(237,118,129)',
        ColorStyle.SUCCESS: 'rgb(107,184,109)',
        ColorStyle.WARNING: 'rgb(143,110,44)',
        ColorStyle.INFO: 'rgb(180,204,245)',
        ColorStyle.HIGHLIGHT: 'rgb(255,255,255)',
        ColorStyle.MAIN: 'rgb(210,210,210)',
        ColorStyle.MUTED: 'rgb(151,153,153)',
        ColorStyle.SEPARATOR: 'rgb(50,50,50)',
        # Todo
        ColorStyle.TODO_COMPLETED: 'rgb(107,184,109)',
        ColorStyle.TODO_IN_PROGRESS: 'rgb(150,204,235)',
        # Tools and agents
        ColorStyle.AGENT_BORDER: 'rgb(110,131,127)',
        # Code
        ColorStyle.DIFF_REMOVED_LINE: 'rgb(255,255,255) on rgb(112,47,55)',
        ColorStyle.DIFF_ADDED_LINE: 'rgb(255,255,255) on rgb(49,91,48)',
        ColorStyle.DIFF_REMOVED_CHAR: 'rgb(255,255,255) on rgb(167,95,107)',
        ColorStyle.DIFF_ADDED_CHAR: 'rgb(255,255,255) on rgb(88,164,102)',
        ColorStyle.CONTEXT_LINE: 'rgb(255,255,255)',
        ColorStyle.INLINE_CODE: 'rgb(180,184,245)',
        # Prompt toolkit
        ColorStyle.INPUT_PLACEHOLDER: 'rgb(151,153,153)',
        ColorStyle.COMPLETION_MENU: 'rgb(154,154,154)',
        ColorStyle.COMPLETION_SELECTED_FG: 'rgb(74,74,74)',
        ColorStyle.COMPLETION_SELECTED_BG: 'rgb(170,221,255)',
        # Input mode colors
        ColorStyle.BASH_MODE: 'rgb(255,102,170)',
        ColorStyle.MEMORY_MODE: 'rgb(200,205,255)',
        ColorStyle.PLAN_MODE: 'rgb(126,184,185)',
        # Markdown
        ColorStyle.H2: 'rgb(221,145,112)',
    }
)


class ConsoleProxy:
    def __init__(self):
        self.console = Console(theme=light_theme, style=ColorStyle.MAIN.value)
        self.silent = False

    def set_theme(self, theme_name: str):
        if theme_name == 'dark':
            self.console = Console(theme=dark_theme, style=ColorStyle.MAIN.value)
        else:
            self.console = Console(theme=light_theme, style=ColorStyle.MAIN.value)

    def print(self, *args, **kwargs):
        if not self.silent:
            self.console.print(*args, **kwargs)

    def set_silent(self, silent: bool):
        self.silent = silent


console = ConsoleProxy()


INTERRUPT_TIP = ' Press ctrl+c to interrupt  '


class PaddingStatus(Status):
    @property
    def renderable(self) -> Group:
        return Group(
            '',
            super().renderable,
        )


def render_status(status: str, spinner: str = 'dots', spinner_style: str = ''):
    return PaddingStatus(Text.assemble(status, (INTERRUPT_TIP, ColorStyle.MUTED.value)), console=console.console, spinner=spinner, spinner_style=spinner_style)


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
        mark = Text(mark, style=ColorStyle.ERROR.value)
    elif status == 'canceled':
        mark = Text(mark, style=ColorStyle.WARNING.value)
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
                line = Text.from_markup(f'{hashes} [bold]{title}[/bold]', style=style if len(hashes) > 2 else ColorStyle.H2.value)
            else:
                line = Text.from_markup(line, style=style + Style(bold=True))
        elif line.strip().startswith('>'):
            quote_content = re.sub(r'^(\s*)>\s?', r'\1', line)
            line = Text.from_markup(f'[muted]▌ {quote_content}[/muted]', style=style)
        elif line.strip() == '---':
            line = Rule(style=ColorStyle.SEPARATOR.value)
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


def render_hello(tips: list[str]) -> RenderResult:
    grid_data = [
        [
            Text('✻', style=ColorStyle.AI_MESSAGE),
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
        Panel.fit(table, border_style=ColorStyle.AI_MESSAGE),
        '',
        render_message(
            '\n'.join(tips),
            mark='※ Tips:',
            style=ColorStyle.MUTED,
            mark_style=ColorStyle.MUTED,
            mark_width=6,
            render_text=True,
        ),
        '',
    )


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
        Text('···', style=ColorStyle.MUTED),
        Text.assemble('+ ', Text(str(middle_lines), style='bold'), ' lines', style=ColorStyle.MUTED),
        Text('···', style=ColorStyle.MUTED),
        tail_content,
    )


def clear_last_line():
    sys.stdout.write('\033[F\033[K')
    sys.stdout.flush()


def get_prompt_toolkit_color(color_style: ColorStyle) -> str:
    """Get hex color value for prompt-toolkit from theme"""
    style_value = console.console.get_style(color_style.value)
    if hasattr(style_value, 'color') and style_value.color:
        # Convert rich Color to hex
        if hasattr(style_value.color, 'triplet'):
            r, g, b = style_value.color.triplet
            return f'#{r:02x}{g:02x}{b:02x}'
        elif hasattr(style_value.color, 'number'):
            # Handle palette colors
            return f'ansi{style_value.color.number}'
    # Fallback to extract from rgb() string
    rgb_match = re.search(r'rgb\((\d+),(\d+),(\d+)\)', str(style_value))
    if rgb_match:
        r, g, b = map(int, rgb_match.groups())
        return f'#{r:02x}{g:02x}{b:02x}'
    return '#ffffff'


def get_prompt_toolkit_style() -> dict:
    """Get prompt-toolkit style dict based on current theme"""
    return {
        'completion-menu': 'bg:default',
        'completion-menu.border': 'bg:default',
        'completion-menu.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.completion.current': f'bg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_FG)} fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_BG)}',
        'scrollbar.background': 'bg:default',
        'scrollbar.button': 'bg:default',
        'completion-menu.meta.completion': f'bg:default fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_MENU)}',
        'completion-menu.meta.completion.current': f'bg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_BG)} fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_FG)}',
    }


def get_inquirer_style() -> dict:
    """Get InquirerPy style dict based on current theme"""
    return {
        'question': f'bold {get_prompt_toolkit_color(ColorStyle.HIGHLIGHT)}',
        'pointer': f'fg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_FG)} bg:{get_prompt_toolkit_color(ColorStyle.COMPLETION_SELECTED_BG)}',
    }
