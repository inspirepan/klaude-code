import json
from pathlib import Path
from typing import Any, cast

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events, model, tools
from klaude_code.protocol.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.ui.renderers import diffs as r_diffs
from klaude_code.ui.renderers.common import create_grid, truncate_display
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.theme import ThemeKey

# Tool markers (Unicode symbols for UI display)
MARK_GENERIC = "⚒"
MARK_BASH = "→"
MARK_PLAN = "▪"
MARK_READ = "←"
MARK_EDIT = "±"
MARK_WRITE = "+"
MARK_MERMAID = "⧉"
MARK_WEB_FETCH = "←"
MARK_WEB_SEARCH = ""
MARK_DONE = "✔"
MARK_SKILL = "✪"

# Todo status markers
MARK_TODO_PENDING = "▢"
MARK_TODO_IN_PROGRESS = "◉"
MARK_TODO_COMPLETED = "✔"


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


def render_generic_tool_call(tool_name: str, arguments: str, markup: str = MARK_GENERIC) -> RenderableType:
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
    tool_name_column = Text.assemble((MARK_BASH, ThemeKey.TOOL_MARK), " ", ("Bash", ThemeKey.TOOL_NAME))

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
    tool_name_column = Text.assemble((MARK_PLAN, ThemeKey.TOOL_MARK), " ", ("Update Plan", ThemeKey.TOOL_NAME))
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
    grid.add_row(Text(MARK_READ, ThemeKey.TOOL_MARK), render_result)
    return grid


def render_edit_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble((MARK_EDIT, ThemeKey.TOOL_MARK), " ", ("Edit", ThemeKey.TOOL_NAME))
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
        tool_name_column = Text.assemble((MARK_WRITE, ThemeKey.TOOL_MARK), " ", ("Write", ThemeKey.TOOL_NAME))
        arguments_column = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    except json.JSONDecodeError:
        tool_name_column = Text.assemble((MARK_WRITE, ThemeKey.TOOL_MARK), " ", ("Write", ThemeKey.TOOL_NAME))
        arguments_column = Text(
            arguments.strip()[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    grid.add_row(tool_name_column, arguments_column)
    return grid


def render_apply_patch_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble((MARK_EDIT, ThemeKey.TOOL_MARK), " ", ("Apply Patch", ThemeKey.TOOL_NAME))

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
        update_count = 0
        add_count = 0
        delete_count = 0
        for line in patch_content.splitlines():
            if line.startswith("*** Update File:"):
                update_count += 1
            elif line.startswith("*** Add File:"):
                add_count += 1
            elif line.startswith("*** Delete File:"):
                delete_count += 1

        parts: list[str] = []
        if update_count > 0:
            parts.append(f"Update File × {update_count}" if update_count > 1 else "Update File")
        if add_count > 0:
            parts.append(f"Add File × {add_count}" if add_count > 1 else "Add File")
        if delete_count > 0:
            parts.append(f"Delete File × {delete_count}" if delete_count > 1 else "Delete File")

        if parts:
            arguments_column = Text(", ".join(parts), ThemeKey.TOOL_PARAM)
    else:
        arguments_column = Text(
            str(patch_content)[: const.INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    grid.add_row(tool_name_column, arguments_column)
    return grid


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

    return Padding.indent(todo_grid, level=2)


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as indented, truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    return Padding.indent(truncate_display(result, base_style=style), level=2)


def _extract_mermaid_link(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.MermaidLinkUIExtra | None:
    if isinstance(ui_extra, model.MermaidLinkUIExtra):
        return ui_extra
    return None


def render_mermaid_tool_call(arguments: str) -> RenderableType:
    grid = create_grid()
    tool_name_column = Text.assemble((MARK_MERMAID, ThemeKey.TOOL_MARK), " ", ("Mermaid", ThemeKey.TOOL_NAME))
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
    tool_name_column = Text.assemble((MARK_WEB_FETCH, ThemeKey.TOOL_MARK), " ", ("Fetch", ThemeKey.TOOL_NAME))

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
    tool_name_column = Text.assemble((MARK_WEB_SEARCH, ThemeKey.TOOL_MARK), " ", ("Web Search", ThemeKey.TOOL_NAME))

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
    tool_name_column = Text.assemble((MARK_DONE, ThemeKey.TOOL_MARK), " ", ("Report Back", ThemeKey.TOOL_NAME))
    grid.add_row(tool_name_column, "")
    return grid


# Tool name to active form mapping (for spinner status)
_TOOL_ACTIVE_FORM: dict[str, str] = {
    tools.BASH: "Bashing",
    tools.APPLY_PATCH: "Patching",
    tools.EDIT: "Editing",
    tools.READ: "Reading",
    tools.WRITE: "Writing",
    tools.TODO_WRITE: "Planning",
    tools.UPDATE_PLAN: "Planning",
    tools.SKILL: "Skilling",
    tools.MERMAID: "Diagramming",
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
        case tools.BASH:
            return render_bash_tool_call(e.arguments)
        case tools.APPLY_PATCH:
            return render_apply_patch_tool_call(e.arguments)
        case tools.TODO_WRITE:
            return render_generic_tool_call("Update Todos", "", MARK_PLAN)
        case tools.UPDATE_PLAN:
            return render_update_plan_tool_call(e.arguments)
        case tools.MERMAID:
            return render_mermaid_tool_call(e.arguments)
        case tools.SKILL:
            return render_generic_tool_call(e.tool_name, e.arguments, MARK_SKILL)
        case tools.REPORT_BACK:
            return render_report_back_tool_call()
        case tools.WEB_FETCH:
            return render_web_fetch_tool_call(e.arguments)
        case tools.WEB_SEARCH:
            return render_web_search_tool_call(e.arguments)
        case _:
            return render_generic_tool_call(e.tool_name, e.arguments)


def _extract_diff(ui_extra: model.ToolResultUIExtra | None) -> model.DiffUIExtra | None:
    if isinstance(ui_extra, model.DiffUIExtra):
        return ui_extra
    return None


def _extract_markdown_doc(ui_extra: model.ToolResultUIExtra | None) -> model.MarkdownDocUIExtra | None:
    if isinstance(ui_extra, model.MarkdownDocUIExtra):
        return ui_extra
    return None


def render_markdown_doc(md_ui: model.MarkdownDocUIExtra, *, code_theme: str) -> RenderableType:
    """Render markdown document content in a panel."""
    return Panel.fit(
        NoInsetMarkdown(md_ui.content, code_theme=code_theme),
        box=box.SIMPLE,
        border_style=ThemeKey.LINES,
        style=ThemeKey.WRITE_MARKDOWN_PANEL,
    )


def render_tool_result(e: events.ToolResultEvent, *, code_theme: str = "monokai") -> RenderableType | None:
    """Unified entry point for rendering tool results.

    Returns a Rich Renderable or None if the tool result should not be rendered.
    """
    from klaude_code.ui.renderers import errors as r_errors

    if is_sub_agent_tool(e.tool_name):
        return None

    # Handle error case
    if e.status == "error" and e.ui_extra is None:
        error_msg = truncate_display(e.result)
        return r_errors.render_error(error_msg)

    # Show truncation info if output was truncated and saved to file
    truncation_info = get_truncation_info(e)
    if truncation_info:
        return Group(render_truncation_info(truncation_info), render_generic_tool_result(e.result))

    diff_ui = _extract_diff(e.ui_extra)
    md_ui = _extract_markdown_doc(e.ui_extra)

    match e.tool_name:
        case tools.READ:
            return None
        case tools.EDIT:
            return Padding.indent(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""), level=2)
        case tools.WRITE:
            if md_ui:
                return Padding.indent(render_markdown_doc(md_ui, code_theme=code_theme), level=2)
            return Padding.indent(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""), level=2)
        case tools.APPLY_PATCH:
            if diff_ui:
                return Padding.indent(r_diffs.render_structured_diff(diff_ui, show_file_name=True), level=2)
            if len(e.result.strip()) == 0:
                return render_generic_tool_result("(no content)")
            return render_generic_tool_result(e.result)
        case tools.TODO_WRITE | tools.UPDATE_PLAN:
            return render_todo(e)
        case tools.MERMAID:
            return render_mermaid_tool_result(e)
        case tools.BASH:
            if e.result.startswith("diff --git"):
                return r_diffs.render_diff_panel(e.result, show_file_name=True)
            if len(e.result.strip()) == 0:
                return render_generic_tool_result("(no content)")
            return render_generic_tool_result(e.result)
        case _:
            if len(e.result.strip()) == 0:
                return render_generic_tool_result("(no content)")
            return render_generic_tool_result(e.result)
