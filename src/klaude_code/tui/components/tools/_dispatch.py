import shutil

from rich import box
from rich.console import Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events, model, tools
from klaude_code.tui.components import diffs as r_diffs
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.quote import TreeQuote
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._bash import render_bash_tool_call
from klaude_code.tui.components.tools._common import (
    is_sub_agent_tool,
    render_fallback_tool_result,
    render_generic_tool_call,
)
from klaude_code.tui.components.tools._file import (
    render_apply_patch_tool_call,
    render_edit_tool_call,
    render_write_tool_call,
)
from klaude_code.tui.components.tools._question import (
    render_ask_user_question_summary,
    render_ask_user_question_tool_call,
    render_ask_user_question_tool_result,
)
from klaude_code.tui.components.tools._read import render_read_preview, render_read_tool_call
from klaude_code.tui.components.tools._rewind import render_rewind_tool_call
from klaude_code.tui.components.tools._todo import render_todo, render_todo_message
from klaude_code.tui.components.tools._web import (
    extract_web_result_for_display,
    render_web_fetch_tool_call,
    render_web_search_tool_call,
)


def _tool_result_display_name(tool_name: str) -> str:
    match tool_name:
        case tools.BASH:
            return "Bash"
        case tools.APPLY_PATCH:
            return "Patch"
        case tools.EDIT:
            return "Edit"
        case tools.READ:
            return "Read"
        case tools.WRITE:
            return "Write"
        case tools.TODO_WRITE:
            return "Update To-Dos"
        case tools.WEB_FETCH:
            return "Fetch Web"
        case tools.WEB_SEARCH:
            return "Search Web"
        case tools.REWIND:
            return "Rewind"
        case tools.ASK_USER_QUESTION:
            return "Agent has a question for you"
        case _:
            return tool_name


def _tool_result_content_indent(tool_name: str) -> int:
    if tool_name in {tools.TODO_WRITE, tools.ASK_USER_QUESTION}:
        return 0
    return len(_tool_result_display_name(tool_name)) + 1


# Tool name to active form mapping (for spinner status)
_TOOL_ACTIVE_FORM: dict[str, str] = {
    tools.BASH: "Bashing",
    tools.APPLY_PATCH: "Patching",
    tools.EDIT: "Editing",
    tools.READ: "Reading",
    tools.WRITE: "Writing",
    tools.TODO_WRITE: "Updating Todos",
    tools.WEB_FETCH: "Fetching Web",
    tools.WEB_SEARCH: "Searching Web",
    tools.AGENT: "Running Task",
    tools.REWIND: "Rewinding",
    tools.ASK_USER_QUESTION: "Questioning",
}


def get_tool_active_form(tool_name: str) -> str:
    """Get the active form of a tool name for spinner status.

    Checks both the static mapping and sub agent profiles.
    """
    if tool_name in _TOOL_ACTIVE_FORM:
        return _TOOL_ACTIVE_FORM[tool_name]

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
            return None
        case tools.REWIND:
            return render_rewind_tool_call(e.arguments)
        case tools.WEB_FETCH:
            return render_web_fetch_tool_call(e.arguments)
        case tools.WEB_SEARCH:
            return render_web_search_tool_call(e.arguments)
        case tools.ASK_USER_QUESTION:
            return render_ask_user_question_tool_call(e.arguments)
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
    """Render markdown document content in a panel with 2-char left indent and top margin."""
    # Limit panel width to min(100, terminal_width) minus left indent (2)
    terminal_width = shutil.get_terminal_size().columns
    panel_width = min(100, terminal_width) - 2

    panel = Panel(
        NoInsetMarkdown(md_ui.content, code_theme=code_theme),
        box=box.SIMPLE,
        border_style=ThemeKey.LINES,
        style=ThemeKey.WRITE_MARKDOWN_PANEL,
        width=panel_width,
    )
    # (top, right, bottom, left) - 1 line top margin, 2-char left indent
    return Padding(panel, (1, 0, 0, 2))


def render_tool_result(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
) -> RenderableType | None:
    """Unified entry point for rendering tool results.

    Returns a Rich Renderable or None if the tool result should not be rendered.
    """
    if is_sub_agent_tool(e.tool_name):
        return None

    def wrap(content: RenderableType) -> TreeQuote:
        return TreeQuote.for_tool_result(
            content,
            is_last=e.is_last_in_turn,
            content_indent=_tool_result_content_indent(e.tool_name),
        )

    # Handle error case
    if e.is_error and e.ui_extra is None:
        if e.tool_name == tools.TODO_WRITE:
            result = e.result if len(e.result.strip()) > 0 else "(no content)"
            return render_todo_message(result, is_error=True)
        return wrap(render_fallback_tool_result(e.tool_name, e.result, is_error=True))

    # Render multiple ui blocks if present
    if isinstance(e.ui_extra, model.MultiUIExtra) and e.ui_extra.items:
        rendered: list[RenderableType] = []
        for item in e.ui_extra.items:
            if isinstance(item, model.MarkdownDocUIExtra):
                # Markdown docs render without TreeQuote wrap (already has 2-char indent)
                rendered.append(render_markdown_doc(item, code_theme=code_theme))
            elif isinstance(item, model.DiffUIExtra):
                show_file_name = e.tool_name == tools.APPLY_PATCH
                rendered.append(wrap(r_diffs.render_structured_diff(item, show_file_name=show_file_name)))
        return Group(*rendered) if rendered else None

    diff_ui = _extract_diff(e.ui_extra)
    md_ui = _extract_markdown_doc(e.ui_extra)

    def _render_fallback() -> TreeQuote:
        if len(e.result.strip()) == 0:
            return wrap(render_fallback_tool_result(e.tool_name, "(no content)"))
        return wrap(render_fallback_tool_result(e.tool_name, e.result, is_error=e.is_error))

    match e.tool_name:
        case tools.READ:
            if isinstance(e.ui_extra, model.ReadPreviewUIExtra):
                return wrap(render_read_preview(e.ui_extra))
            return None
        case tools.EDIT:
            return wrap(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""))
        case tools.WRITE:
            if md_ui:
                # Markdown docs render without TreeQuote wrap (already has 2-char indent)
                return render_markdown_doc(md_ui, code_theme=code_theme)
            return wrap(r_diffs.render_structured_diff(diff_ui) if diff_ui else Text(""))
        case tools.APPLY_PATCH:
            if md_ui:
                # Markdown docs render without TreeQuote wrap (already has 2-char indent)
                return render_markdown_doc(md_ui, code_theme=code_theme)
            if diff_ui:
                return wrap(r_diffs.render_structured_diff(diff_ui, show_file_name=True))
            return _render_fallback()
        case tools.TODO_WRITE:
            if isinstance(e.ui_extra, model.TodoListUIExtra):
                return render_todo(e)
            result = e.result if len(e.result.strip()) > 0 else "(no content)"
            return render_todo_message(result, is_error=e.is_error)
        case tools.BASH:
            return wrap(render_fallback_tool_result(e.tool_name, e.result, is_error=e.is_error))
        case tools.WEB_FETCH | tools.WEB_SEARCH:
            display_result = extract_web_result_for_display(e.result)
            if len(display_result.strip()) == 0:
                return wrap(render_fallback_tool_result(e.tool_name, "(no content)"))
            return wrap(render_fallback_tool_result(e.tool_name, display_result, is_error=e.is_error))
        case tools.ASK_USER_QUESTION:
            if isinstance(e.ui_extra, model.AskUserQuestionSummaryUIExtra):
                return render_ask_user_question_summary(e.ui_extra)
            if len(e.result.strip()) == 0:
                return wrap(render_fallback_tool_result(e.tool_name, "(no content)"))
            return wrap(render_ask_user_question_tool_result(e.result, is_error=e.is_error))
        case _:
            return _render_fallback()
