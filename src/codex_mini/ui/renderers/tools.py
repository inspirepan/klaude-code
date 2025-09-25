import json
from typing import Optional

from rich import box
from rich.box import Box
from rich.color import Color
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from codex_mini.protocol import events, model
from codex_mini.ui.mdstream import NoInsetMarkdown
from codex_mini.ui.quote import Quote
from codex_mini.ui.renderers.common import create_grid, truncate_display
from codex_mini.ui.theme import ThemeKey


def render_path(path: str, style: str, is_directory: bool = False) -> Text:
    from pathlib import Path

    if path.startswith(str(Path().cwd())):
        path = path.replace(str(Path().cwd()), "").lstrip("/")
    elif path.startswith(str(Path().home())):
        path = path.replace(str(Path().home()), "~")
    elif not path.startswith("/") and not path.startswith("."):
        path = "./" + path
    if is_directory:
        path = path.rstrip("/") + "/"
    return Text(path, style=style)


def render_generic_tool_call(tool_name: str, arguments: str, markup: str = "•") -> RenderableType:
    grid = create_grid()

    tool_name_column = Text.assemble((markup, ThemeKey.TOOL_MARK), " ", (tool_name, ThemeKey.TOOL_NAME))
    arguments_column = Text("")
    if not arguments:
        grid.add_row(tool_name_column, arguments_column)
        return grid
    try:
        json_dict = json.loads(arguments)
        if len(json_dict) == 0:
            arguments_column = Text("", ThemeKey.TOOL_PARAM)
        elif len(json_dict) == 1:
            arguments_column = Text(str(next(iter(json_dict.values()))), ThemeKey.TOOL_PARAM)
        else:
            arguments_column = Text(", ".join([f"{k}: {v}" for k, v in json_dict.items()]), ThemeKey.TOOL_PARAM)
    except json.JSONDecodeError:
        arguments_column = Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS)
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_read_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    render_result: Text = Text.assemble(("Read", ThemeKey.TOOL_NAME), " ")
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        limit = json_dict.get("limit", None)
        offset = json_dict.get("offset", None)
        render_result = render_result.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        if limit is not None and offset is not None:
            render_result = (
                render_result.append_text(Text(" "))
                .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text(str(offset + limit - 1), ThemeKey.TOOL_PARAM_BOLD))
            )
        elif limit is not None:
            render_result = (
                render_result.append_text(Text(" "))
                .append_text(Text("1", ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text(str(limit), ThemeKey.TOOL_PARAM_BOLD))
            )
        elif offset is not None:
            render_result = (
                render_result.append_text(Text(" "))
                .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text("-", ThemeKey.TOOL_PARAM_BOLD))
            )
    except json.JSONDecodeError:
        render_result = render_result.append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
    grid.add_row(Text("←", ThemeKey.TOOL_MARK), render_result)
    return grid


def render_edit_tool_call(arguments: str) -> Text:
    render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK))
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        old_string = json_dict.get("old_string", "")
        render_result = (
            render_result.append_text(Text("Create" if old_string == "" else "Edit", ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        )
    except json.JSONDecodeError:
        render_result = (
            render_result.append_text(Text("Edit", ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
        )
    return render_result


def render_multi_edit_tool_call(arguments: str) -> Text:
    render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK), ("MultiEdit", ThemeKey.TOOL_NAME), " ")
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        edits = json_dict.get("edits", [])
        render_result = (
            render_result.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
            .append_text(Text(" - "))
            .append_text(Text(f"{len(edits)}", ThemeKey.TOOL_PARAM_BOLD))
            .append_text(Text(" updates", ThemeKey.TOOL_PARAM_FILE_PATH))
        )
    except json.JSONDecodeError:
        render_result = render_result.append_text(Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS))
    return render_result


def render_plan(arguments: str, *, box_style: Box | None = None, code_theme: str) -> RenderableType:
    if box_style is None:
        box_style = box.ROUNDED
    # Plan mode
    try:
        json_dict = json.loads(arguments)
        plan = json_dict.get("plan", "")
        return Group(
            Text.assemble(("¶ ", ThemeKey.TOOL_MARK), ("Plan", ThemeKey.TOOL_NAME)),
            Panel.fit(NoInsetMarkdown(plan, code_theme=code_theme), border_style=ThemeKey.LINES, box=box_style),
        )
    except json.JSONDecodeError:
        return Text.assemble(
            ("¶ ", ThemeKey.TOOL_MARK),
            ("Plan", ThemeKey.TOOL_NAME),
            " ",
            Text(arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS),
        )


def render_task_call(e: events.ToolCallEvent, color: Color | None = None) -> RenderableType:
    """Render Task/Oracle tool call header and quoted body.

    `color` can be a Rich Color instance or color name string; it's used only for the
    reversed description segment.
    """
    try:
        json_dict = json.loads(e.arguments)
        description = json_dict.get("description", "")
        prompt = json_dict.get("prompt", "")
        context = json_dict.get("context", "")
        task = json_dict.get("task", "")

        desc = Text(f" {description} ", style=Style(color=color, bold=True, reverse=True))
        body = Quote(
            Text("\n".join(filter(None, [context, task, prompt])), style=Style(color=color)), style=Style(color=color)
        )
        return Group(Text.assemble(("↓ ", ThemeKey.TOOL_MARK), (e.tool_name, ThemeKey.TOOL_NAME), " ", desc), body)

    except json.JSONDecodeError:
        return Text.assemble(
            ("↓ ", ThemeKey.TOOL_MARK),
            ("Task", ThemeKey.TOOL_NAME),
            " ",
            Text(e.arguments, style=ThemeKey.INVALID_TOOL_CALL_ARGS),
        )


def render_todo(tr: events.ToolResultEvent) -> RenderableType:
    if tr.ui_extra is None:
        return Text.assemble(("  ✘", ThemeKey.ERROR_BOLD), " ", Text("(no content)", style=ThemeKey.ERROR))
    try:
        ui_extra = model.TodoUIExtra.model_validate_json(tr.ui_extra)
        grid = create_grid()
        for todo in ui_extra.todos:
            is_new_completed = todo.content in ui_extra.new_completed
            match todo.status:
                case "pending":
                    mark = "▢"
                    mark_style = ThemeKey.TODO_PENDING_MARK
                    text_style = ThemeKey.TODO_PENDING
                case "in_progress":
                    mark = "◉"
                    mark_style = ThemeKey.TODO_IN_PROGRESS_MARK
                    text_style = ThemeKey.TODO_IN_PROGRESS
                case "completed":
                    mark = "✔"
                    mark_style = ThemeKey.TODO_NEW_COMPLETED_MARK if is_new_completed else ThemeKey.TODO_COMPLETED_MARK
                    text_style = ThemeKey.TODO_NEW_COMPLETED if is_new_completed else ThemeKey.TODO_COMPLETED
            text = Text(todo.content)
            text.stylize(text_style)
            grid.add_row(Text(mark, style=mark_style), text)
        return Padding.indent(grid, level=2)
    except json.JSONDecodeError as e:
        return Text(str(e), style=ThemeKey.ERROR)


def render_task_result(e: events.ToolResultEvent, *, quote_style: Style, code_theme: str) -> RenderableType:
    # For sub-agent
    return Quote(NoInsetMarkdown(e.result, code_theme=code_theme), style=quote_style)


def render_exit_plan_result(status: str, ui_extra: Optional[str]) -> RenderableType:
    grid = create_grid()
    if status == "success":
        approved = Padding.indent(Text(" Approved ", ThemeKey.TOOL_APPROVED), level=1)
        grid.add_row(
            Text("↓", style=ThemeKey.METADATA),
            Text("execute with ", style=ThemeKey.METADATA).append_text(
                Text(ui_extra or "N/A", style=ThemeKey.METADATA_BOLD)
            ),
        )
        return Group(approved, grid)
    else:
        rejected = Padding.indent(Text(" Rejected ", ThemeKey.TOOL_REJECTED), level=1)
        return rejected


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as indented, truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    return Padding.indent(Text(truncate_display(result), style=style), level=2)
