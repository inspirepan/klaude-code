import json

from rich import box
from rich.console import RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code.const import INVALID_TOOL_CALL_MAX_LENGTH, TAB_EXPAND_WIDTH
from klaude_code.protocol import events, model
from klaude_code.tui.components.common import create_grid
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import MARK_PLAN, render_tool_call_tree

# Todo status markers
MARK_TODO_PENDING = "\u25a2"
MARK_TODO_IN_PROGRESS = "\u25c9"
MARK_TODO_COMPLETED = "\u2714"


def render_todo_write_tool_call(arguments: str) -> RenderableType:
    tool_name = "Update To-Dos"
    details: RenderableType | None = None

    if arguments:
        try:
            json.loads(arguments)
        except json.JSONDecodeError:
            details = Text(
                arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            )

    return render_tool_call_tree(mark=MARK_PLAN, tool_name=tool_name, details=details)


def render_todo(tr: events.ToolResultEvent) -> RenderableType:
    assert isinstance(tr.ui_extra, model.TodoListUIExtra)
    ui_extra = tr.ui_extra.todo_list
    todo_grid = create_grid()
    for todo in ui_extra.todos:
        is_new_completed = todo.content in ui_extra.new_completed
        match todo.status:
            case "pending":
                mark = MARK_TODO_PENDING
                mark_style = ThemeKey.TODO_PENDING_MARK
                text_style = ThemeKey.TODO_PENDING
            case "in_progress":
                mark = MARK_TODO_IN_PROGRESS
                mark_style = ThemeKey.TODO_IN_PROGRESS_MARK
                text_style = ThemeKey.TODO_IN_PROGRESS
            case "completed":
                mark = MARK_TODO_COMPLETED
                mark_style = ThemeKey.TODO_NEW_COMPLETED_MARK if is_new_completed else ThemeKey.TODO_COMPLETED_MARK
                text_style = ThemeKey.TODO_NEW_COMPLETED if is_new_completed else ThemeKey.TODO_COMPLETED
        text = Text(todo.content)
        text.stylize(text_style)
        todo_grid.add_row(Text(mark, style=mark_style), text)

    return Panel(
        Padding(todo_grid, (0, 0, 0, 1)),
        title=Text("Update To-Dos", style="default bold"),
        title_align="left",
        box=box.ROUNDED,
        border_style=ThemeKey.LINES,
        expand=False,
    )


def render_todo_message(result: str, *, is_error: bool = False) -> RenderableType:
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    return Panel(
        Padding(Text(result.expandtabs(TAB_EXPAND_WIDTH), style=style, overflow="fold"), (0, 0, 0, 1)),
        title=Text("Update To-Dos", style="default bold"),
        title_align="left",
        box=box.ROUNDED,
        border_style=ThemeKey.LINES,
        expand=False,
    )
