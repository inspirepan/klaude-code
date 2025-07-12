from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.style import Style
from rich.table import Table
from rich.text import Text

from .colors import ColorStyle, get_all_themes, get_theme


def show_theme_preview(theme_name: str) -> Panel:
    """Return a preview panel of the specified theme"""
    # Create a new console with the specified theme
    theme_console = Console(theme=get_theme(theme_name), style=ColorStyle.MAIN)

    rule_style = theme_console.get_style(ColorStyle.LINE.value)

    # Create preview content using the themed console
    preview_table = Table.grid(padding=(0, 2))
    preview_table.add_column()

    # Diff example
    diff_section = _create_diff_section(theme_console)
    preview_table.add_row(diff_section)
    preview_table.add_row('')

    preview_table.add_row(Rule(style=rule_style, characters='╌'))

    # Message type examples
    message_section = _create_message_section(theme_console)
    preview_table.add_row(message_section)
    preview_table.add_row('')

    preview_table.add_row(Rule(style=rule_style, characters='╌'))

    # Todo list examples
    todo_section = _create_todo_section(theme_console)
    preview_table.add_row(todo_section)

    # Create and return preview panel with themed title

    panel = Panel.fit(preview_table, title=Text(theme_name, style='white bold'), border_style='bright_black')
    return panel


def show_all_theme_previews() -> Columns:
    """Return columns of all theme previews"""
    panels = []
    for theme_name in get_all_themes():
        panel = show_theme_preview(theme_name)
        panels.append(panel)

    return Columns(panels, expand=True, padding=(0, 1))


def _create_diff_section(theme_console: Console) -> Table:
    """Create code diff example"""
    diff_table = Table.grid()
    diff_table.add_column()

    # Title
    header_style = theme_console.get_style(ColorStyle.HIGHLIGHT.value)
    diff_table.add_row(Text('Code Diff', style=header_style + Style(bold=True)))
    diff_table.add_row('')

    # Example diff
    removed_style = theme_console.get_style(ColorStyle.DIFF_REMOVED_LINE.value)
    added_style = theme_console.get_style(ColorStyle.DIFF_ADDED_LINE.value)
    context_style = theme_console.get_style(ColorStyle.CONTEXT_LINE.value)

    removed_line = Text('- def old_function():', style=removed_style)
    added_line = Text('+ def new_function():', style=added_style)
    context_line = Text('    return result', style=context_style)

    diff_table.add_row(removed_line)
    diff_table.add_row(added_line)
    diff_table.add_row(context_line)

    return diff_table


def _create_message_section(theme_console: Console) -> Table:
    """Create message type examples"""
    msg_table = Table.grid()
    msg_table.add_column()

    # Title
    header_style = theme_console.get_style(ColorStyle.HIGHLIGHT.value)
    msg_table.add_row(Text('Messages', style=header_style + Style(bold=True)))
    msg_table.add_row('')

    # Different message types
    user_style = theme_console.get_style(ColorStyle.USER_MESSAGE.value)
    ai_style = theme_console.get_style(ColorStyle.AI_CONTENT.value)
    tool_style = theme_console.get_style(ColorStyle.TOOL_NAME.value)

    user_msg = Text('User: Hello!', style=user_style)
    ai_msg = Text('AI: Hello! I am Klaude Code', style=ai_style)
    tool_msg = Text('Tool: bash execution result', style=tool_style)

    msg_table.add_row(user_msg)
    msg_table.add_row(ai_msg)
    msg_table.add_row(tool_msg)

    return msg_table


def _create_todo_section(theme_console: Console) -> Table:
    """Create todo list examples"""
    todo_table = Table.grid()
    todo_table.add_column()

    # Title
    header_style = theme_console.get_style(ColorStyle.HIGHLIGHT.value)
    todo_table.add_row(Text('Todo List', style=header_style + Style(bold=True)))
    todo_table.add_row('')

    # Different todo statuses
    completed_style = theme_console.get_style(ColorStyle.TODO_COMPLETED.value)
    in_progress_style = theme_console.get_style(ColorStyle.TODO_IN_PROGRESS.value)

    # Completed todo (with strikethrough)
    completed = Text.from_markup('☒ [s]Implement feature X[/s]', style=completed_style)

    # Recently completed todo (highlighted)
    new_completed = Text.from_markup('☒ [s]Fix critical bug[/s]', style=completed_style)

    # In progress todo (bold)
    in_progress = Text.from_markup('☐ [bold]Review code changes[/bold]', style=in_progress_style)

    # Pending todo (normal)
    pending = Text('☐ Update documentation')

    todo_table.add_row(completed)
    todo_table.add_row(new_completed)
    todo_table.add_row(in_progress)
    todo_table.add_row(pending)

    return todo_table
