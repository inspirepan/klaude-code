from rich import box
from rich.console import Group, RenderableType
from rich.constrain import Constrain
from rich.padding import Padding
from rich.panel import Panel
from rich.text import Text

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import (
    AskUserQuestionSummaryUIExtra,
    DiffUIExtra,
    MarkdownDocUIExtra,
    MultiUIExtra,
    ReadPreviewUIExtra,
    TodoListUIExtra,
    ToolResultUIExtra,
)
from klaude_code.tui.components import diffs as r_diffs
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._bash import render_bash_tool_call
from klaude_code.tui.components.tools._common import (
    TOOL_RESULT_INDENT,
    TOOL_SUBJECT_INDENT,
    AdaptiveIndent,
    is_sub_agent_tool,
    render_fallback_tool_result,
    render_generic_tool_call,
    render_path,
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
    parse_web_search_results,
    render_web_fetch_tool_call,
    render_web_search_results,
    render_web_search_tool_call,
)
from klaude_code.tui.transcript_detail import Detail

_COMPACT_MARKDOWN_PREVIEW_LINES = 5
# Upper bound on result panels, so they read as one consistent column instead
# of each box sizing itself to its longest line.
RESULT_PANEL_MAX_WIDTH = 100


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
    tools.HANDOFF: "Packing Context",
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


def _extract_diff(ui_extra: ToolResultUIExtra | None) -> DiffUIExtra | None:
    if isinstance(ui_extra, DiffUIExtra):
        return ui_extra
    if isinstance(ui_extra, MultiUIExtra):
        for item in ui_extra.items:
            if isinstance(item, DiffUIExtra):
                return item
    return None


def _extract_markdown_doc(ui_extra: ToolResultUIExtra | None) -> MarkdownDocUIExtra | None:
    if isinstance(ui_extra, MarkdownDocUIExtra):
        return ui_extra
    if isinstance(ui_extra, MultiUIExtra):
        for item in ui_extra.items:
            if isinstance(item, MarkdownDocUIExtra):
                return item
    return None


def _render_result_panel(
    content: RenderableType,
    *,
    title: Text | None = None,
    indent: int = TOOL_RESULT_INDENT,
) -> RenderableType:
    """The one box used for every block-level tool result (diffs, docs, search)."""
    # Constrain, not fix: the panel still shrinks to short content, but one long
    # line (a deep path, say) can no longer stretch it across the whole terminal
    # and leave the rest of the box looking empty.
    return Padding(
        Constrain(
            Panel(
                content,
                title=title,
                title_align="left",
                box=box.ROUNDED,
                border_style=ThemeKey.LINES,
                expand=False,
            ),
            RESULT_PANEL_MAX_WIDTH,
        ),
        (0, 0, 0, indent),
        expand=False,
    )


def render_markdown_doc(
    md_ui: MarkdownDocUIExtra,
    *,
    code_theme: str,
    detail: Detail = Detail.FULL,
    show_file_path: bool = False,
    indent: int = TOOL_RESULT_INDENT,
) -> RenderableType:
    """Render a Markdown document preview in the file-change panel."""
    title = render_path(md_ui.file_path, ThemeKey.TOOL_PARAM_FILE_PATH) if show_file_path else None
    if title is not None:
        title.no_wrap = True
        title.overflow = "ellipsis"

    if detail.is_compact:
        lines = md_ui.content.splitlines()
        hidden_lines = max(0, len(lines) - _COMPACT_MARKDOWN_PREVIEW_LINES)
        preview: list[RenderableType] = [
            Text(line, style=ThemeKey.TOOL_RESULT, no_wrap=True, overflow="ellipsis")
            for line in lines[:_COMPACT_MARKDOWN_PREVIEW_LINES]
        ]
        if hidden_lines:
            preview.append(Text(f"\u2026 (more {hidden_lines} lines)", style=ThemeKey.TOOL_RESULT_TRUNCATED))
        return _render_result_panel(Group(*preview), title=title, indent=indent)

    return _render_result_panel(
        NoInsetMarkdown(md_ui.content, code_theme=code_theme, style=ThemeKey.TOOL_RESULT),
        title=title,
        indent=indent,
    )


def _file_change_count(ui_extra: ToolResultUIExtra | None) -> int:
    items = ui_extra.items if isinstance(ui_extra, MultiUIExtra) else [ui_extra]
    return sum(len(item.files) if isinstance(item, DiffUIExtra) else 1 for item in items if item is not None)


def render_compact_file_change_action(e: events.ToolResultEvent, action: str) -> Text:
    """Render a sub-agent file action with a single target or multi-file count."""
    rendered = Text()
    rendered.append(action, style=ThemeKey.TOOL_NAME)
    items = e.ui_extra.items if isinstance(e.ui_extra, MultiUIExtra) else [e.ui_extra]
    markdown_docs = [item for item in items if isinstance(item, MarkdownDocUIExtra)]
    diff_files = [file for item in items if isinstance(item, DiffUIExtra) for file in item.files]
    file_count = len(markdown_docs) + len(diff_files)

    if file_count == 1:
        file_path = markdown_docs[0].file_path if markdown_docs else diff_files[0].file_path
        rendered.append(" ")
        rendered.append_text(render_path(file_path, ThemeKey.TOOL_PARAM_FILE_PATH))
        if diff_files:
            file_diff = diff_files[0]
            stats = Text()
            if file_diff.stats_add:
                stats.append(f"+{file_diff.stats_add}", style=ThemeKey.DIFF_STATS_ADD)
            if file_diff.stats_remove:
                if stats:
                    stats.append(" ")
                stats.append(f"-{file_diff.stats_remove}", style=ThemeKey.DIFF_STATS_REMOVE)
            if stats:
                rendered.append(" (")
                rendered.append_text(stats)
                rendered.append(")")
    elif file_count > 1:
        rendered.append(f" · {file_count} files", style=ThemeKey.METADATA_DIM)
    return rendered


def render_tool_result(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
    detail: Detail = Detail.COMPACT,
) -> RenderableType | None:
    """Unified entry point for rendering tool results.

    Returns a Rich Renderable or None if the tool result should not be rendered.
    """
    if is_sub_agent_tool(e.tool_name):
        return None

    def pad_result(content: RenderableType) -> RenderableType:
        # To-Do lists have no call line of their own, so render them at the
        # block-result level. Everything else lines up under its arguments.
        indent = TOOL_RESULT_INDENT if e.tool_name == tools.TODO_WRITE else TOOL_SUBJECT_INDENT
        return AdaptiveIndent(content, indent)

    # Handle error case
    if e.is_error and e.ui_extra is None:
        if e.tool_name == tools.TODO_WRITE:
            result = e.result if len(e.result.strip()) > 0 else "(no content)"
            return pad_result(render_todo_message(result, status=e.status))
        return pad_result(render_fallback_tool_result(e.tool_name, e.result, status=e.status))

    # Render multiple ui blocks if present
    if isinstance(e.ui_extra, MultiUIExtra) and e.ui_extra.items:
        rendered: list[RenderableType] = []
        show_patch_file_names = e.tool_name == tools.APPLY_PATCH and _file_change_count(e.ui_extra) > 1
        for item in e.ui_extra.items:
            if isinstance(item, MarkdownDocUIExtra):
                # Markdown docs already include their own 2-character indent.
                rendered.append(
                    render_markdown_doc(
                        item,
                        code_theme=code_theme,
                        detail=detail,
                        show_file_path=show_patch_file_names,
                    )
                )
            elif isinstance(item, DiffUIExtra):
                rendered.append(
                    _render_result_panel(
                        r_diffs.render_structured_diff(
                            item,
                            show_file_name=show_patch_file_names,
                            detail=detail,
                        )
                    )
                )
        return Group(*rendered) if rendered else None

    diff_ui = _extract_diff(e.ui_extra)
    md_ui = _extract_markdown_doc(e.ui_extra)

    def _render_fallback() -> RenderableType:
        if len(e.result.strip()) == 0:
            return pad_result(render_fallback_tool_result(e.tool_name, "(no content)"))
        return pad_result(render_fallback_tool_result(e.tool_name, e.result, status=e.status))

    match e.tool_name:
        case tools.READ:
            if isinstance(e.ui_extra, ReadPreviewUIExtra):
                return pad_result(render_read_preview(e.ui_extra))
            return None
        case tools.EDIT:
            return _render_result_panel(r_diffs.render_structured_diff(diff_ui, detail=detail) if diff_ui else Text(""))
        case tools.WRITE:
            if md_ui:
                # Markdown docs already include their own 2-character indent.
                return render_markdown_doc(md_ui, code_theme=code_theme, detail=detail)
            return _render_result_panel(r_diffs.render_structured_diff(diff_ui, detail=detail) if diff_ui else Text(""))
        case tools.APPLY_PATCH:
            if md_ui:
                # Markdown docs already include their own 2-character indent.
                return render_markdown_doc(md_ui, code_theme=code_theme, detail=detail)
            if diff_ui:
                return _render_result_panel(
                    r_diffs.render_structured_diff(
                        diff_ui,
                        show_file_name=len(diff_ui.files) > 1,
                        detail=detail,
                    )
                )
            return _render_fallback()
        case tools.TODO_WRITE:
            if isinstance(e.ui_extra, TodoListUIExtra):
                return pad_result(render_todo(e))
            result = e.result if len(e.result.strip()) > 0 else "(no content)"
            return pad_result(render_todo_message(result, status=e.status))
        case tools.BASH:
            return _render_fallback()
        case tools.WEB_SEARCH:
            search_results = parse_web_search_results(e.result)
            if search_results:
                return _render_result_panel(render_web_search_results(search_results, detail=detail))
            display_result = extract_web_result_for_display(e.result)
            if len(display_result.strip()) == 0:
                return pad_result(render_fallback_tool_result(e.tool_name, "(no content)"))
            return pad_result(render_fallback_tool_result(e.tool_name, display_result, status=e.status))
        case tools.WEB_FETCH:
            display_result = extract_web_result_for_display(e.result)
            if len(display_result.strip()) == 0:
                return pad_result(render_fallback_tool_result(e.tool_name, "(no content)"))
            return pad_result(render_fallback_tool_result(e.tool_name, display_result, status=e.status))
        case tools.ASK_USER_QUESTION:
            if isinstance(e.ui_extra, AskUserQuestionSummaryUIExtra):
                return AdaptiveIndent(render_ask_user_question_summary(e.ui_extra), TOOL_RESULT_INDENT)
            if len(e.result.strip()) == 0:
                return pad_result(render_fallback_tool_result(e.tool_name, "(no content)"))
            return pad_result(render_ask_user_question_tool_result(e.result, status=e.status))
        case _:
            return _render_fallback()


def render_compact_file_change(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
) -> RenderableType | None:
    """Render diffs and new Markdown documents from a compact sub-agent result."""

    items = e.ui_extra.items if isinstance(e.ui_extra, MultiUIExtra) else [e.ui_extra]
    show_file_names = _file_change_count(e.ui_extra) > 1
    rendered: list[RenderableType] = []
    for item in items:
        # Flush with the sub-agent header: the block's gutter and the panel border
        # already mark the nesting, so an extra indent would be a third boundary.
        if isinstance(item, DiffUIExtra):
            rendered.append(
                _render_result_panel(
                    r_diffs.render_structured_diff(
                        item,
                        show_file_name=show_file_names,
                        detail=Detail.COMPACT,
                    ),
                    indent=0,
                )
            )
        elif e.tool_name in (tools.WRITE, tools.APPLY_PATCH) and isinstance(item, MarkdownDocUIExtra):
            rendered.append(
                render_markdown_doc(
                    item,
                    code_theme=code_theme,
                    detail=Detail.COMPACT,
                    show_file_path=show_file_names,
                    indent=0,
                )
            )
    if not rendered:
        return None
    return Group(*rendered)
