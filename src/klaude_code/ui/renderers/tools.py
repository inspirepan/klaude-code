import json
from pathlib import Path

from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code.core.subagent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.protocol import events, model
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.renderers.common import create_grid, truncate_display

INVALID_TOOL_CALL_MAX_LENGTH = 500


def is_sub_agent_tool(tool_name: str) -> bool:
    return _is_sub_agent_tool(tool_name)


def render_path(path: str, style: str, is_directory: bool = False) -> Text:
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
        arguments_column = Text(arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_update_plan_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("◎", ThemeKey.TOOL_MARK), " ", ("Update Plan", ThemeKey.TOOL_NAME))
    explanation_column = Text("")

    if arguments:
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError:
            explanation_column = Text(
                arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS
            )
        else:
            explanation = payload.get("explanation")
            if isinstance(explanation, str) and explanation.strip():
                explanation_column = Text(explanation.strip(), style=ThemeKey.TODO_EXPLANATION)

    grid.add_row(tool_name_column, explanation_column)
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
        render_result = render_result.append_text(
            Text(arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)
        )
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
            .append_text(Text(arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS))
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
        render_result = render_result.append_text(
            Text(arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)
        )
    return render_result


def render_apply_patch_tool_call(arguments: str) -> RenderableType:
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        return Text.assemble(
            ("→ ", ThemeKey.TOOL_MARK),
            ("Apply Patch", ThemeKey.TOOL_NAME),
            " ",
            Text(arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS),
        )

    patch_content = payload.get("patch", "")

    grid = create_grid()
    header = Text.assemble(("→ ", ThemeKey.TOOL_MARK), ("Apply Patch", ThemeKey.TOOL_NAME))
    summary = Text("", ThemeKey.TOOL_PARAM)

    if isinstance(patch_content, str):
        lines = [line for line in patch_content.splitlines() if line and not line.startswith("*** Begin Patch")]
        if lines:
            summary = Text(lines[0][:INVALID_TOOL_CALL_MAX_LENGTH], ThemeKey.TOOL_PARAM)
    else:
        summary = Text(str(patch_content)[:INVALID_TOOL_CALL_MAX_LENGTH], ThemeKey.INVALID_TOOL_CALL_ARGS)

    if summary.plain:
        grid.add_row(header, summary)
    else:
        grid.add_row(header, Text("", ThemeKey.TOOL_PARAM))

    return grid


def render_todo(tr: events.ToolResultEvent) -> RenderableType:
    if tr.ui_extra is None:
        return Text.assemble(("  ✘", ThemeKey.ERROR_BOLD), " ", Text("(no content)", style=ThemeKey.ERROR))
    try:
        ui_extra = model.TodoUIExtra.model_validate_json(tr.ui_extra)
        todo_grid = create_grid()
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
            todo_grid.add_row(Text(mark, style=mark_style), text)

        return Padding.indent(todo_grid, level=2)
    except json.JSONDecodeError as e:
        return Text(str(e), style=ThemeKey.ERROR)


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as indented, truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    return Padding.indent(Text(truncate_display(result), style=style), level=2)
