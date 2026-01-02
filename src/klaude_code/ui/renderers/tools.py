import json
from pathlib import Path
from typing import Any, cast

from rich import box
from rich.console import Group, RenderableType
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from klaude_code.const import (
    BASH_OUTPUT_PANEL_THRESHOLD,
    INVALID_TOOL_CALL_MAX_LENGTH,
    QUERY_DISPLAY_TRUNCATE_LENGTH,
    URL_TRUNCATE_MAX_LENGTH,
    WEB_SEARCH_DEFAULT_MAX_RESULTS,
)
from klaude_code.protocol import events, model, tools
from klaude_code.protocol.sub_agent import is_sub_agent_tool as _is_sub_agent_tool
from klaude_code.ui.renderers import diffs as r_diffs
from klaude_code.ui.renderers import mermaid_viewer as r_mermaid_viewer
from klaude_code.ui.renderers.bash_syntax import highlight_bash_command
from klaude_code.ui.renderers.common import create_grid, truncate_middle
from klaude_code.ui.rich.code_panel import CodePanel
from klaude_code.ui.rich.markdown import NoInsetMarkdown
from klaude_code.ui.rich.quote import TreeQuote
from klaude_code.ui.rich.theme import ThemeKey

# Tool markers (Unicode symbols for UI display)
MARK_GENERIC = "⚒"
MARK_BASH = "$"
MARK_PLAN = "◈"
MARK_READ = "→"
MARK_EDIT = "±"
MARK_WRITE = "+"
MARK_MOVE = "±"
MARK_MERMAID = "⧉"
MARK_WEB_FETCH = "→"
MARK_WEB_SEARCH = "✱"
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


def _render_tool_call_tree(
    *,
    mark: str,
    tool_name: str,
    details: RenderableType | None,
) -> RenderableType:
    grid = create_grid(overflow="ellipsis")
    grid.add_row(
        Text(tool_name, style=ThemeKey.TOOL_NAME),
        details if details is not None else Text(""),
    )

    return TreeQuote.for_tool_call(
        grid,
        mark=mark,
        style=ThemeKey.TOOL_RESULT_TREE_PREFIX,
        style_first=ThemeKey.TOOL_MARK,
    )


def render_generic_tool_call(tool_name: str, arguments: str, markup: str = MARK_GENERIC) -> RenderableType:
    if not arguments:
        return _render_tool_call_tree(mark=markup, tool_name=tool_name, details=None)

    details: RenderableType
    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    else:
        if isinstance(payload, dict):
            payload_dict = cast(dict[str, Any], payload)
            if len(payload_dict) == 0:
                details = Text("", ThemeKey.TOOL_PARAM)
            elif len(payload_dict) == 1:
                details = Text(str(next(iter(payload_dict.values()))), ThemeKey.TOOL_PARAM)
            else:
                details = Text(
                    ", ".join([f"{k}: {v}" for k, v in payload_dict.items()]),
                    ThemeKey.TOOL_PARAM,
                )
        else:
            details = Text(str(payload)[:INVALID_TOOL_CALL_MAX_LENGTH], style=ThemeKey.INVALID_TOOL_CALL_ARGS)

    return _render_tool_call_tree(mark=markup, tool_name=tool_name, details=details)


def render_bash_tool_call(arguments: str) -> RenderableType:
    tool_name = "Bash"

    try:
        payload_raw: Any = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError:
        details: RenderableType = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=details)

    if not isinstance(payload_raw, dict):
        details = Text(
            str(payload_raw)[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=details)

    payload: dict[str, object] = cast(dict[str, object], payload_raw)

    command = payload.get("command")
    timeout_ms = payload.get("timeout_ms")

    if isinstance(command, str) and command.strip():
        cmd_str = command.strip()
        line_count = len(cmd_str.splitlines())

        highlighted = highlight_bash_command(cmd_str)

        if line_count > BASH_OUTPUT_PANEL_THRESHOLD:
            code_panel = CodePanel(highlighted, border_style=ThemeKey.LINES)
            if isinstance(timeout_ms, int):
                if timeout_ms >= 1000 and timeout_ms % 1000 == 0:
                    timeout_text = Text(f"{timeout_ms // 1000}s", style=ThemeKey.TOOL_TIMEOUT)
                else:
                    timeout_text = Text(f"{timeout_ms}ms", style=ThemeKey.TOOL_TIMEOUT)
                return _render_tool_call_tree(
                    mark=MARK_BASH,
                    tool_name=tool_name,
                    details=Group(code_panel, timeout_text),
                )
            else:
                return _render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=code_panel)
        if isinstance(timeout_ms, int):
            if timeout_ms >= 1000 and timeout_ms % 1000 == 0:
                highlighted.append(f" {timeout_ms // 1000}s", style=ThemeKey.TOOL_TIMEOUT)
            else:
                highlighted.append(f" {timeout_ms}ms", style=ThemeKey.TOOL_TIMEOUT)
        return _render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=highlighted)
    else:
        summary = Text("", ThemeKey.TOOL_PARAM)
        if isinstance(timeout_ms, int):
            if timeout_ms >= 1000 and timeout_ms % 1000 == 0:
                summary.append(f"{timeout_ms // 1000}s", style=ThemeKey.TOOL_TIMEOUT)
            else:
                summary.append(f"{timeout_ms}ms", style=ThemeKey.TOOL_TIMEOUT)
        bash_details: RenderableType | None = summary if summary.plain else None
        return _render_tool_call_tree(mark=MARK_BASH, tool_name=tool_name, details=bash_details)


def render_update_plan_tool_call(arguments: str) -> RenderableType:
    tool_name = "Update Plan"
    details: RenderableType | None = None

    if arguments:
        try:
            payload = json.loads(arguments)
        except json.JSONDecodeError:
            details = Text(
                arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
                style=ThemeKey.INVALID_TOOL_CALL_ARGS,
            )
        else:
            explanation = payload.get("explanation")
            if isinstance(explanation, str) and explanation.strip():
                details = Text(explanation.strip(), style=ThemeKey.TODO_EXPLANATION)

    return _render_tool_call_tree(mark=MARK_PLAN, tool_name=tool_name, details=details)


def render_read_tool_call(arguments: str) -> RenderableType:
    tool_name = "Read"
    details = Text("", ThemeKey.TOOL_PARAM)
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        limit = json_dict.get("limit", None)
        offset = json_dict.get("offset", None)
        if isinstance(file_path, str) and file_path:
            details.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        else:
            details.append("(no file_path)", style=ThemeKey.TOOL_PARAM)
        if limit is not None and offset is not None:
            details = (
                details.append_text(Text(" "))
                .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text(str(offset + limit - 1), ThemeKey.TOOL_PARAM_BOLD))
            )
        elif limit is not None:
            details = (
                details.append_text(Text(" "))
                .append_text(Text("1", ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text(str(limit), ThemeKey.TOOL_PARAM_BOLD))
            )
        elif offset is not None:
            details = (
                details.append_text(Text(" "))
                .append_text(Text(str(offset), ThemeKey.TOOL_PARAM_BOLD))
                .append_text(Text(":", ThemeKey.TOOL_PARAM))
                .append_text(Text("-", ThemeKey.TOOL_PARAM_BOLD))
            )
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    return _render_tool_call_tree(mark=MARK_READ, tool_name=tool_name, details=details)


def render_edit_tool_call(arguments: str) -> RenderableType:
    tool_name = "Edit"
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path")
        replace_all = json_dict.get("replace_all", False)
        path_text = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
        if replace_all:
            old_string = json_dict.get("old_string", "")
            new_string = json_dict.get("new_string", "")
            replace_info = Text("Replacing all ", ThemeKey.TOOL_RESULT_TRUNCATED)
            replace_info.append(old_string, ThemeKey.BASH_STRING)
            replace_info.append(" → ", ThemeKey.BASH_OPERATOR)
            replace_info.append(new_string, ThemeKey.BASH_STRING)
            details: RenderableType = Group(path_text, replace_info)
        else:
            details = path_text
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    return _render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)


def render_write_tool_call(arguments: str) -> RenderableType:
    tool_name = "Write"
    try:
        json_dict = json.loads(arguments)
        file_path = json_dict.get("file_path", "")
        # Markdown files show path in result panel, skip here to avoid duplication
        if file_path.endswith(".md"):
            details: RenderableType | None = None
        else:
            details = render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    return _render_tool_call_tree(mark=MARK_WRITE, tool_name=tool_name, details=details)


def render_move_tool_call(arguments: str) -> RenderableType:
    tool_name = "Move"

    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_MOVE, tool_name=tool_name, details=details)

    source_path = payload.get("source_file_path", "")
    target_path = payload.get("target_file_path", "")
    start_line = payload.get("start_line", "")
    end_line = payload.get("end_line", "")

    parts = Text()
    if source_path:
        parts.append_text(render_path(source_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        if start_line and end_line:
            parts.append(f":{start_line}-{end_line}", style=ThemeKey.TOOL_PARAM)
    parts.append(" -> ", style=ThemeKey.TOOL_PARAM)
    if target_path:
        parts.append_text(render_path(target_path, ThemeKey.TOOL_PARAM_FILE_PATH))

    return _render_tool_call_tree(mark=MARK_MOVE, tool_name=tool_name, details=parts)


def render_apply_patch_tool_call(arguments: str) -> RenderableType:
    tool_name = "Apply Patch"

    try:
        payload = json.loads(arguments)
    except json.JSONDecodeError:
        details = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)

    patch_content = payload.get("patch", "")
    details = Text("", ThemeKey.TOOL_PARAM)

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
            details = Text(", ".join(parts), ThemeKey.TOOL_PARAM)
    else:
        details = Text(
            str(patch_content)[:INVALID_TOOL_CALL_MAX_LENGTH],
            ThemeKey.INVALID_TOOL_CALL_ARGS,
        )

    return _render_tool_call_tree(mark=MARK_EDIT, tool_name=tool_name, details=details)


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

    return todo_grid


def render_generic_tool_result(result: str, *, is_error: bool = False) -> RenderableType:
    """Render a generic tool result as truncated text."""
    style = ThemeKey.ERROR if is_error else ThemeKey.TOOL_RESULT
    text = truncate_middle(result, base_style=style)
    # Tool results should not reflow/wrap; use ellipsis when exceeding terminal width.
    text.no_wrap = True
    text.overflow = "ellipsis"
    return text


def _extract_mermaid_link(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.MermaidLinkUIExtra | None:
    return ui_extra if isinstance(ui_extra, model.MermaidLinkUIExtra) else None


def render_mermaid_tool_call(arguments: str) -> RenderableType:
    tool_name = "Mermaid"
    summary = Text("", ThemeKey.TOOL_PARAM)

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
    else:
        code = payload.get("code", "")
        if code:
            line_count = len(code.splitlines())
            summary = Text(f"{line_count} lines", ThemeKey.TOOL_PARAM)
        else:
            summary = Text("0 lines", ThemeKey.TOOL_PARAM)

    return _render_tool_call_tree(mark=MARK_MERMAID, tool_name=tool_name, details=summary)


def _truncate_url(url: str, max_length: int = URL_TRUNCATE_MAX_LENGTH) -> str:
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
    return display_url[: max_length - 1] + "…"


def _render_mermaid_viewer_link(
    tr: events.ToolResultEvent,
    link_info: model.MermaidLinkUIExtra,
    *,
    use_osc8: bool,
) -> RenderableType:
    viewer_path = r_mermaid_viewer.build_viewer(code=link_info.code, link=link_info.link, tool_call_id=tr.tool_call_id)
    if viewer_path is None:
        return Text(link_info.link, style=ThemeKey.TOOL_RESULT_MERMAID, overflow="ellipsis", no_wrap=True)

    display_path = str(viewer_path)

    file_url = ""
    if use_osc8:
        try:
            file_url = viewer_path.resolve().as_uri()
        except ValueError:
            file_url = f"file://{viewer_path.as_posix()}"

    rendered = Text.assemble(("View diagram in ", ThemeKey.TOOL_RESULT), " ")
    start = len(rendered)
    rendered.append(display_path, ThemeKey.TOOL_RESULT_MERMAID)
    end = len(rendered)

    if use_osc8 and file_url:
        rendered.stylize(Style(link=file_url), start, end)

    return rendered


def render_web_fetch_tool_call(arguments: str) -> RenderableType:
    tool_name = "Fetch"

    try:
        payload: dict[str, str] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_WEB_FETCH, tool_name=tool_name, details=summary)

    url = payload.get("url", "")
    summary = Text(_truncate_url(url), ThemeKey.TOOL_PARAM_FILE_PATH) if url else Text("(no url)", ThemeKey.TOOL_PARAM)

    return _render_tool_call_tree(mark=MARK_WEB_FETCH, tool_name=tool_name, details=summary)


def render_web_search_tool_call(arguments: str) -> RenderableType:
    tool_name = "Web Search"

    try:
        payload: dict[str, Any] = json.loads(arguments)
    except json.JSONDecodeError:
        summary = Text(
            arguments.strip()[:INVALID_TOOL_CALL_MAX_LENGTH],
            style=ThemeKey.INVALID_TOOL_CALL_ARGS,
        )
        return _render_tool_call_tree(mark=MARK_WEB_SEARCH, tool_name=tool_name, details=summary)

    query = payload.get("query", "")
    max_results = payload.get("max_results")

    summary = Text("", ThemeKey.TOOL_PARAM)
    if query:
        # Truncate long queries
        display_query = (
            query if len(query) <= QUERY_DISPLAY_TRUNCATE_LENGTH else query[: QUERY_DISPLAY_TRUNCATE_LENGTH - 1] + "…"
        )
        summary.append(display_query, ThemeKey.TOOL_PARAM)
    else:
        summary.append("(no query)", ThemeKey.TOOL_PARAM)

    if isinstance(max_results, int) and max_results != WEB_SEARCH_DEFAULT_MAX_RESULTS:
        summary.append(f" (max {max_results})", ThemeKey.TOOL_TIMEOUT)

    return _render_tool_call_tree(mark=MARK_WEB_SEARCH, tool_name=tool_name, details=summary)


def render_mermaid_tool_result(
    tr: events.ToolResultEvent,
    *,
    session_id: str | None = None,
) -> RenderableType:
    from klaude_code.ui.terminal import supports_osc8_hyperlinks

    link_info = _extract_mermaid_link(tr.ui_extra)
    if link_info is None:
        return render_generic_tool_result(tr.result, is_error=tr.status == "error")

    use_osc8 = supports_osc8_hyperlinks()
    viewer = _render_mermaid_viewer_link(tr, link_info, use_osc8=use_osc8)

    return viewer


def _extract_truncation(
    ui_extra: model.ToolResultUIExtra | None,
) -> model.TruncationUIExtra | None:
    return ui_extra if isinstance(ui_extra, model.TruncationUIExtra) else None


def render_truncation_info(ui_extra: model.TruncationUIExtra) -> RenderableType:
    """Render truncation info for the user."""
    truncated_kb = ui_extra.truncated_length / 1024

    text = Text.assemble(
        ("Offload context to ", ThemeKey.TOOL_RESULT_TRUNCATED),
        (ui_extra.saved_file_path, ThemeKey.TOOL_RESULT_TRUNCATED),
        (f", {truncated_kb:.1f}KB truncated", ThemeKey.TOOL_RESULT_TRUNCATED),
    )
    text.no_wrap = True
    text.overflow = "ellipsis"
    return text


def get_truncation_info(tr: events.ToolResultEvent) -> model.TruncationUIExtra | None:
    """Extract truncation info from a tool result event."""
    return _extract_truncation(tr.ui_extra)


def render_report_back_tool_call() -> RenderableType:
    return _render_tool_call_tree(mark=MARK_DONE, tool_name="Report Back", details=None)


# Tool name to active form mapping (for spinner status)
_TOOL_ACTIVE_FORM: dict[str, str] = {
    tools.BASH: "Bashing",
    tools.APPLY_PATCH: "Patching",
    tools.MOVE: "Moving",
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
        case tools.MOVE:
            return render_move_tool_call(e.arguments)
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
    if isinstance(ui_extra, model.MultiUIExtra):
        for item in ui_extra.items:
            if isinstance(item, model.DiffUIExtra):
                return item
    return None


def _extract_markdown_doc(ui_extra: model.ToolResultUIExtra | None) -> model.MarkdownDocUIExtra | None:
    if isinstance(ui_extra, model.MarkdownDocUIExtra):
        return ui_extra
    if isinstance(ui_extra, model.MultiUIExtra):
        for item in ui_extra.items:
            if isinstance(item, model.MarkdownDocUIExtra):
                return item
    return None


def render_markdown_doc(md_ui: model.MarkdownDocUIExtra, *, code_theme: str) -> RenderableType:
    """Render markdown document content in a panel."""
    header = render_path(md_ui.file_path, ThemeKey.TOOL_PARAM_FILE_PATH)
    return Panel.fit(
        Group(header, Text(""), NoInsetMarkdown(md_ui.content, code_theme=code_theme)),
        box=box.SIMPLE,
        border_style=ThemeKey.LINES,
        style=ThemeKey.WRITE_MARKDOWN_PANEL,
    )


def render_tool_result(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
    session_id: str | None = None,
) -> RenderableType | None:
    """Unified entry point for rendering tool results.

    Returns a Rich Renderable or None if the tool result should not be rendered.
    """
    if is_sub_agent_tool(e.tool_name):
        return None

    def wrap(content: RenderableType) -> TreeQuote:
        return TreeQuote.for_tool_result(content, is_last=e.is_last_in_turn)

    # Handle error case
    if e.status == "error" and e.ui_extra is None:
        return wrap(render_generic_tool_result(e.result, is_error=True))

    # Render multiple ui blocks if present
    if isinstance(e.ui_extra, model.MultiUIExtra) and e.ui_extra.items:
        rendered: list[RenderableType] = []
        for item in e.ui_extra.items:
            if isinstance(item, model.MarkdownDocUIExtra):
                rendered.append(render_markdown_doc(item, code_theme=code_theme))
            elif isinstance(item, model.DiffUIExtra):
                show_file_name = e.tool_name in (tools.APPLY_PATCH, tools.MOVE)
                rendered.append(r_diffs.render_structured_diff(item, show_file_name=show_file_name))
        return wrap(Group(*rendered)) if rendered else None

    # Show truncation info if output was truncated and saved to file
    truncation_info = get_truncation_info(e)
    if truncation_info:
        result = render_generic_tool_result(e.result, is_error=e.status == "error")
        return wrap(Group(render_truncation_info(truncation_info), result))

    diff_ui = _extract_diff(e.ui_extra)
    md_ui = _extract_markdown_doc(e.ui_extra)

    def _render_fallback() -> TreeQuote:
        if len(e.result.strip()) == 0:
            return wrap(render_generic_tool_result("(no content)"))
        return wrap(render_generic_tool_result(e.result, is_error=e.status == "error"))

    match e.tool_name:
        case tools.READ:
            return None
        case tools.EDIT:
            return wrap(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""))
        case tools.WRITE:
            if md_ui:
                return wrap(render_markdown_doc(md_ui, code_theme=code_theme))
            return wrap(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""))
        case tools.MOVE:
            # Same-file move returns single DiffUIExtra, cross-file returns MultiUIExtra (handled above)
            if diff_ui:
                return wrap(r_diffs.render_structured_diff(diff_ui, show_file_name=True))
            return None
        case tools.APPLY_PATCH:
            if md_ui:
                return wrap(render_markdown_doc(md_ui, code_theme=code_theme))
            if diff_ui:
                return wrap(r_diffs.render_structured_diff(diff_ui, show_file_name=True))
            return _render_fallback()
        case tools.TODO_WRITE | tools.UPDATE_PLAN:
            return wrap(render_todo(e))
        case tools.MERMAID:
            return wrap(render_mermaid_tool_result(e, session_id=session_id))
        case tools.BASH:
            if e.result.startswith("diff --git"):
                return wrap(r_diffs.render_diff_panel(e.result, show_file_name=True))
            return _render_fallback()
        case _:
            return _render_fallback()
