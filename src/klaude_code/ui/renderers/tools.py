import json
from pathlib import Path
from typing import Any, cast

from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events, model, tools
from klaude_code.protocol.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.ui.renderers import diffs as r_diffs
from klaude_code.ui.renderers.common import create_grid
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.utils.common import truncate_display


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
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_bash_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble((">", ThemeKey.TOOL_MARK), " ", ("Bash", ThemeKey.TOOL_NAME))

    try:
        payload_raw: Any = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, summary)
        return grid

    if not isinstance(payload_raw, dict):
        summary = Text(
            str(payload_raw)[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, summary)
        return grid

    payload: dict[str, object] = cast(dict[str, object], payload_raw)

    summary = Text("", ThemeKey.TOOL_PARAM)
    command = payload.get("command")
    timeout_ms = payload.get("timeout_ms")

    if isinstance(command, str) and command.strip():
        summary.append(command.strip(), style=ThemeKey.TOOL_PARAM)

    if isinstance(timeout_ms, int):
        if summary:
            summary.append(" ")
        if timeout_ms >= 1000 and timeout_ms % 1000 == 0:
            summary.append(f"{timeout_ms // 1000}s", style=ThemeKey.TOOL_TIMEOUT)
        else:
            summary.append(f"{timeout_ms}ms", style=ThemeKey.TOOL_TIMEOUT)

    grid.add_row(tool_name_column, summary)
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
                arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
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
                arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            )
        )
    grid.add_row(Text("←", ThemeKey.TOOL_MARK), render_result)
    return grid


def render_edit_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("→", ThemeKey.TOOL_MARK), " ", ("Edit", ThemeKey.TOOL_NAME))
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        arguments_column = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    except json.JSONDecodeError:
        arguments_column = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_write_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        tool_name_column = Text.assemble(("→", ThemeKey.TOOL_MARK), " ", ("Write", ThemeKey.TOOL_NAME))
        arguments_column = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    except json.JSONDecodeError:
        tool_name_column = Text.assemble(("→", ThemeKey.TOOL_MARK), " ", ("Write", ThemeKey.TOOL_NAME))
        arguments_column = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_multi_edit_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("→", ThemeKey.TOOL_MARK), " ", ("MultiEdit", ThemeKey.TOOL_NAME))
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        edits = json_dict.get("edits", [])
        arguments_column = Text.assemble(
            render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH),
            Text(" - "),
            Text(f"{len(edits)}", ThemeKey.TOOL_PARAM_BOLD),
            Text(" updates", ThemeKey.TOOL_PARAM_FILE_PATH),
        )
    except json.JSONDecodeError:
        arguments_column = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_apply_patch_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("→", ThemeKey.TOOL_MARK), " ", ("Apply Patch", ThemeKey.TOOL_NAME))

    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        arguments_column = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, arguments_column)
        return grid

    patch_content = payload.get("patch", "")
    arguments_column = Text("", ThemeKey.TOOL_PARAM)

    if isinstance(patch_content, str):
        lines = [line for line in patch_content.splitlines() if line and not line.startswith("*** Begin Patch")]
        if lines:
            arguments_column = Text(lines[0][: const.INVALID_TOOL_CALL_MAX_LENGTH], ThemeKey.TOOL_PARAM)
    else:
        arguments_column = Text(
            str(patch_content)[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_todo(tr: events.ToolResultEvent) -> RenderableType:
    if not isinstance(tr.ui_extra, model.TodoListUIExtra):
        return Text.assemble(
            ("  ✘", ThemeKey.ERROR_BOLD),
            " ",
            Text("(no content)" if tr.ui_extra is None else "(invalid ui_extra)", style=ThemeKey.ERROR),
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
            case _:
                mark = "?"
                mark_style = ThemeKey.TODO_PENDING_MARK
                text_style = ThemeKey.TODO_PENDING
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
    if isinstance(ui_extra, model.MermaidLinkUIExtra):
        return ui_extra
    return None


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
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
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
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
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


def _truncate_url(url: str, max_length: int = 400) -> str:
    """Truncate URL for display, preserving domain and path structure."""
    if len(url) <= max_length:
        return url
    # Remove protocol for display
    display_url = url
    for prefix in ("https://", "http://"):
        if display_url.startswith(prefix):
            display_url = display_url[len(prefix) :]
            break
    if len(display_url) <= max_length:
        return display_url
    # Truncate with ellipsis
    return display_url[: max_length - 3] + "..."


def render_web_fetch_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("↓", ThemeKey.TOOL_MARK), " ", ("Fetch", ThemeKey.TOOL_NAME))

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, summary)
        return grid

    url = payload.get("url", "")
    summary = Text(_truncate_url(url), ThemeKey.TOOL_PARAM_FILE_PATH) if url else Text("(no url)", ThemeKey.TOOL_PARAM)

    grid.add_row(tool_name_column, summary)
    return grid


def render_web_search_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("◉", ThemeKey.TOOL_MARK), " ", ("Search", ThemeKey.TOOL_NAME))

    try:
        payload: dict[str, Any] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        grid.add_row(tool_name_column, summary)
        return grid

    query = payload.get("query", "")
    max_results = payload.get("max_results")

    summary = Text("", ThemeKey.TOOL_PARAM)
    if query:
        # Truncate long queries
        display_query = query if len(query) <= 80 else query[:77] + "..."
        summary.append(display_query, ThemeKey.TOOL_PARAM)
    else:
        summary.append("(no query)", ThemeKey.TOOL_PARAM)

    if isinstance(max_results, int) and max_results != 10:
        summary.append(f" (max {max_results})", ThemeKey.TOOL_TIMEOUT)

    grid.add_row(tool_name_column, summary)
    return grid


def render_mermaid_tool_result(tr: events.ToolResultEvent) -> RenderableType:
    from klaude_code.ui.terminal import supports_osc8_hyperlinks

    link_info = _extract_mermaid_link(tr.ui_extra)
    if link_info is None:
        return render_generic_tool_result(tr.result, is_error=tr.status == "error")

    if supports_osc8_hyperlinks():
        link_text = Text.from_markup(f"[blue u][link={link_info.link}]Command+click to view[/link][/blue u]")
        return Padding.indent(link_text, level=2)

    # For terminals that don't support OSC 8, show a hint to use /export
    hint_text = Text.assemble(
        ("Use ", ThemeKey.TOOL_RESULT),
        ("/export", ThemeKey.TOOL_RESULT_BOLD),
        (" to view the diagram.", ThemeKey.TOOL_RESULT),
    )
    return Padding.indent(hint_text, level=2)


def _extract_truncation(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.TruncationUIExtra | None:
    if isinstance(ui_extra, model.TruncationUIExtra):
        return ui_extra
    return None


def render_truncation_info(ui_extra: model.TruncationUIExtra) -> RenderableType:
    """Render truncation info for the user."""
    truncated_kb = ui_extra.truncated_length / 1024

    text = Text.assemble(
        ("Offload context to ", ThemeKey.TOOL_RESULT_TRUNCATED),
        (ui_extra.saved_file_path, ThemeKey.TOOL_RESULT_TRUNCATED),
        (f", {truncated_kb:.1f}KB truncated", ThemeKey.TOOL_RESULT_TRUNCATED),
    )
    return Padding.indent(text, level=2)


def get_truncation_info(tr: events.ToolResultEvent) -> model.TruncationUIExtra | None:
    """Extract truncation info from a tool result event."""
    return _extract_truncation(tr.ui_extra)


def render_report_back_tool_call() -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble(("✔", ThemeKey.TOOL_MARK), " ", ("Report Back", ThemeKey.TOOL_NAME))
    grid.add_row(tool_name_column, "")
    return grid


# Tool name to active form mapping (for spinner status)
_TOOL_ACTIVE_FORM: dict[str, str] = {
    tools.BASH: "Bashing",
    tools.APPLY_PATCH: "Patching",
    tools.EDIT: "Editing",
    tools.MULTI_EDIT: "Editing",
    tools.READ: "Reading",
    tools.WRITE: "Writing",
    tools.TODO_WRITE: "Planning",
    tools.UPDATE_PLAN: "Planning",
    tools.SKILL: "Skilling",
    tools.MERMAID: "Diagramming",
    tools.MEMORY: "Memorizing",
    tools.WEB_FETCH: "Fetching Web",
    tools.WEB_SEARCH: "Searching Web",
    tools.REPORT_BACK: "Reporting",
}


def get_tool_active_form(tool_name: str) -> str:
    """Get the active form of a tool name for spinner status.

    Checks both the static mapping and sub agent profiles.
    """
    if tool_name in _TOOL_ACTIVE_FORM:
        return _TOOL_ACTIVE_FORM[tool_name]

    # Check sub agent profiles
    from klaude_code.protocol.sub_agent import get_sub_agent_profile_by_tool

    profile = get_sub_agent_profile_by_tool(tool_name)
    if profile and profile.active_form:
        return profile.active_form

    return f"Calling {tool_name}"


def render_tool_call(e: events.ToolCallEvent) -> RenderableType | None:
    """Unified entry point for rendering tool calls.

    Returns a Rich Renderable or None if the tool call should not be rendered.
    """

    if is_sub_agent_tool(e.tool_name):
        return None

    match e.tool_name:
        case tools.READ:
            return render_read_tool_call(e.arguments)
        case tools.EDIT:
            return render_edit_tool_call(e.arguments)
        case tools.WRITE:
            return render_write_tool_call(e.arguments)
        case tools.MULTI_EDIT:
            return render_multi_edit_tool_call(e.arguments)
        case tools.BASH:
            return render_bash_tool_call(e.arguments)
        case tools.APPLY_PATCH:
            return render_apply_patch_tool_call(e.arguments)
        case tools.TODO_WRITE:
            return render_generic_tool_call("Update Todos", "", "◎")
        case tools.UPDATE_PLAN:
            return render_update_plan_tool_call(e.arguments)
        case tools.MERMAID:
            return render_mermaid_tool_call(e.arguments)
        case tools.MEMORY:
            return render_memory_tool_call(e.arguments)
        case tools.SKILL:
            return render_generic_tool_call(e.tool_name, e.arguments, "◈")
        case tools.REPORT_BACK:
            return render_report_back_tool_call()
        case tools.WEB_FETCH:
            return render_web_fetch_tool_call(e.arguments)
        case tools.WEB_SEARCH:
            return render_web_search_tool_call(e.arguments)
        case _:
            return render_generic_tool_call(e.tool_name, e.arguments)


def _extract_diff_text(ui_extra: model.ToolResultUIExtra | None) -> str | None:
    if isinstance(ui_extra, model.DiffTextUIExtra):
        return ui_extra.diff_text
    return None


def render_tool_result(e: events.ToolResultEvent) -> RenderableType | None:
    """Unified entry point for rendering tool results.

    Returns a Rich Renderable or None if the tool result should not be rendered.
    """
    from klaude_code.ui.renderers import errors as r_errors

    if is_sub_agent_tool(e.tool_name):
        return None

    # Handle error case
    if e.status == "error" and e.ui_extra is None:
        error_msg = Text(truncate_display(e.result))
        return r_errors.render_error(error_msg)

    # Show truncation info if output was truncated and saved to file
    truncation_info = get_truncation_info(e)
    if truncation_info:
        return Group(render_truncation_info(truncation_info), render_generic_tool_result(e.result))

    diff_text = _extract_diff_text(e.ui_extra)

    match e.tool_name:
        case tools.READ:
            return None
        case tools.EDIT | tools.MULTI_EDIT | tools.WRITE:
            return Padding.indent(r_diffs.render_diff(diff_text or ""), level=2)
        case tools.MEMORY:
            if diff_text:
                return Padding.indent(r_diffs.render_diff(diff_text), level=2)
            elif len(e.result.strip()) > 0:
                return render_generic_tool_result(e.result)
            return None
        case tools.TODO_WRITE | tools.UPDATE_PLAN:
            return render_todo(e)
        case tools.MERMAID:
            return render_mermaid_tool_result(e)
        case _:
            if e.tool_name in (tools.BASH, tools.APPLY_PATCH) and e.result.startswith("diff --git"):
                return r_diffs.render_diff_panel(e.result, show_file_name=True)
            if e.tool_name == tools.APPLY_PATCH and diff_text:
                return Padding.indent(r_diffs.render_diff(diff_text, show_file_name=True), level=2)
            if len(e.result.strip()) == 0:
                return render_generic_tool_result("(no content)")
            return render_generic_tool_result(e.result)
