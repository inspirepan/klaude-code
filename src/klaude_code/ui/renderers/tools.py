import json
from pathlib import Path

from rich.console import RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code import const
from klaude_code.core.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.protocol import events, model
from klaude_code.ui.base.theme import ThemeKey
from klaude_code.ui.renderers.common import create_grid, truncate_display


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
            arguments_column = Text(
                ", ".join([f"{k}: {v}" for k, v in json_dict.items()]),
                ThemeKey.TOOL_PARAM,
            )
    except json.JSONDecodeError:
        arguments_column = Text(
            arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
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
                arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
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
            Text(
                arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            )
        )
    grid.add_row(Text("←", ThemeKey.TOOL_MARK), render_result)
    return grid


def render_edit_tool_call(arguments: str) -> Text:
    render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK))
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        render_result = (
            render_result.append_text(Text("Edit", ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        )
    except json.JSONDecodeError:
        render_result = (
            render_result.append_text(Text("Edit", ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(
                Text(
                    arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                    style=ThemeKey.INVALID_TOOL_CALL_ARGS,
                )
            )
        )
    return render_result


def render_write_tool_call(arguments: str) -> Text:
    render_result: Text = Text.assemble(("→ ", ThemeKey.TOOL_MARK))
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        op_label = "Create"
        if isinstance(file_path, str):
            abs_path = Path(file_path)
            if not abs_path.is_absolute():
                abs_path = (Path().cwd() / abs_path).resolve()
            if abs_path.exists():
                op_label = "Overwrite"
        render_result = (
            render_result.append_text(Text(op_label, ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        )
    except json.JSONDecodeError:
        render_result = (
            render_result.append_text(Text("Write", ThemeKey.TOOL_NAME))
            .append_text(Text(" "))
            .append_text(
                Text(
                    arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                    style=ThemeKey.INVALID_TOOL_CALL_ARGS,
                )
            )
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
            Text(
                arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            )
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
            Text(
                arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            ),
        )

    patch_content = payload.get("patch", "")

    grid = create_grid()
    header = Text.assemble(("→ ", ThemeKey.TOOL_MARK), ("Apply Patch", ThemeKey.TOOL_NAME))
    summary = Text("", ThemeKey.TOOL_PARAM)

    if isinstance(patch_content, str):
        lines = [line for line in patch_content.splitlines() if line and not line.startswith("*** Begin Patch")]
        if lines:
            summary = Text(lines[0][:const.INVALID_TOOL_CALL_MAX_LENGTH], ThemeKey.TOOL_PARAM)
    else:
        summary = Text(
            str(patch_content)[:const.INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    if summary.plain:
        grid.add_row(header, summary)
    else:
        grid.add_row(header, Text("", ThemeKey.TOOL_PARAM))

    return grid


def render_todo(tr: events.ToolResultEvent) -> RenderableType:
    if tr.ui_extra is None:
        return Text.assemble(
            ("  ✘", ThemeKey.ERROR_BOLD),
            " ",
            Text("(no content)", style=ThemeKey.ERROR),
        )
    if tr.ui_extra.type != model.ToolResultUIExtraType.TODO_LIST or tr.ui_extra.todo_list is None:
        return Text.assemble(
            ("  ✘", ThemeKey.ERROR_BOLD),
            " ",
            Text("(invalid ui_extra)", style=ThemeKey.ERROR),
        )

    ui_extra = tr.ui_extra.todo_list
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


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as indented, truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    return Padding.indent(Text(truncate_display(result), style=style), level=2)


def _extract_mermaid_link(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.MermaidLinkUIExtra | None:
    if ui_extra is None:
        return None
    if ui_extra.type != model.ToolResultUIExtraType.MERMAID_LINK:
        return None
    return ui_extra.mermaid_link


def render_memory_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    command_display_names: dict[str, str] = {
        "view": "View",
        "create": "Create",
        "str_replace": "Replace",
        "insert": "Insert",
        "delete": "Delete",
        "rename": "Rename",
    }

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        tool_name_column = Text.assemble(("★", ThemeKey.TOOL_MARK), " ", ("Memory", ThemeKey.TOOL_NAME))
        summary = Text(
            arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, summary)
        return grid

    command = payload.get("command", "")
    display_name = command_display_names.get(command, command.title())
    tool_name_column = Text.assemble(("★", ThemeKey.TOOL_MARK), " ", (f"{display_name} Memory", ThemeKey.TOOL_NAME))

    summary = Text("", ThemeKey.TOOL_PARAM)
    path = payload.get("path")
    old_path = payload.get("old_path")
    new_path = payload.get("new_path")

    if command == "rename" and old_path and new_path:
        summary = Text.assemble(
            Text(old_path, ThemeKey.TOOL_PARAM_FILE_PATH),
            Text(" -> ", ThemeKey.TOOL_PARAM),
            Text(new_path, ThemeKey.TOOL_PARAM_FILE_PATH),
        )
    elif command == "insert" and path:
        insert_line = payload.get("insert_line")
        summary = Text(path, ThemeKey.TOOL_PARAM_FILE_PATH)
        if insert_line is not None:
            summary.append(f" line {insert_line}", ThemeKey.TOOL_PARAM)
    elif command == "view" and path:
        view_range = payload.get("view_range")
        summary = Text(path, ThemeKey.TOOL_PARAM_FILE_PATH)
        if view_range and isinstance(view_range, list) and len(view_range) >= 2:
            summary.append(f" {view_range[0]}:{view_range[1]}", ThemeKey.TOOL_PARAM)
    elif path:
        summary = Text(path, ThemeKey.TOOL_PARAM_FILE_PATH)

    grid.add_row(tool_name_column, summary)
    return grid


def render_mermaid_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("⧉", ThemeKey.TOOL_MARK), " ", ("Mermaid", ThemeKey.TOOL_NAME))
    summary = Text("", ThemeKey.TOOL_PARAM)

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    else:
        code = payload.get("code", "")
        if code:
            line_count = len(code.splitlines())
            summary = Text(f"{line_count} lines", ThemeKey.TOOL_PARAM)
        else:
            summary = Text("0 lines", ThemeKey.TOOL_PARAM)

    grid.add_row(tool_name_column, summary)
    return grid


def render_mermaid_tool_result(tr: events.ToolResultEvent) -> RenderableType:
    link_info = _extract_mermaid_link(tr.ui_extra)
    if link_info is None:
        return render_generic_tool_result(tr.result, is_error=tr.status == "error")

    link_text = Text.from_markup(f"[blue u][link={link_info.link}]Command+click to view[/link][/blue u]")
    return Padding.indent(link_text, level=2)


def _extract_truncation(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.TruncationUIExtra | None:
    if ui_extra is None:
        return None
    if ui_extra.type != model.ToolResultUIExtraType.TRUNCATION:
        return None
    return ui_extra.truncation


def render_truncation_info(ui_extra: model.TruncationUIExtra) -> RenderableType:
    """Render truncation info for the user."""
    original_kb = ui_extra.original_length / 1024
    truncated_kb = ui_extra.truncated_length / 1024
    text = Text.assemble(
        ("Output truncated: ", ThemeKey.TOOL_RESULT),
        (f"{original_kb:.1f}KB", ThemeKey.TOOL_RESULT),
        (" total, ", ThemeKey.TOOL_RESULT),
        (f"{truncated_kb:.1f}KB", ThemeKey.TOOL_RESULT_BOLD),
        (" hidden\nFull output saved to ", ThemeKey.TOOL_RESULT),
        (ui_extra.saved_file_path, ThemeKey.TOOL_RESULT),
        ("\nUse Read with limit+offset or rg/grep to inspect", ThemeKey.TOOL_RESULT),
    )
    return Padding.indent(text, level=2)


def get_truncation_info(tr: events.ToolResultEvent) -> model.TruncationUIExtra | None:
    """Extract truncation info from a tool result event."""
    return _extract_truncation(tr.ui_extra)
