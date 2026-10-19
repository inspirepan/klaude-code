from typing import TYPE_CHECKING

from pydantic import BaseModel
from rich.console import Group, RenderableType
from rich.text import Text

from klaude_code.protocol import events, tools
from klaude_code.protocol.background_task import ACTIVE_TASK_STATUSES
from klaude_code.protocol.models import (
    AskUserQuestionSummaryUIExtra,
    DiffUIExtra,
    MarkdownDocUIExtra,
    MultiUIExtra,
    ReadPreviewUIExtra,
    TodoListUIExtra,
    ToolResultUIExtra,
    WebSearchUIExtra,
)
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tui.components import diffs as r_diffs
from klaude_code.tui.components.rich.markdown import NoInsetMarkdown
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._bash import render_bash_tool_call
from klaude_code.tui.components.tools._common import (
    FULL_TOOL_RESULT_MAX_LINES,
    TOOL_RESULT_INDENT,
    TOOL_SUBJECT_INDENT,
    AdaptiveIndent,
    is_sub_agent_tool,
    render_fallback_tool_result,
    render_generic_tool_call,
    render_path,
    render_result_panel,
)
from klaude_code.tui.components.tools._file import (
    render_apply_patch_tool_call,
    render_edit_tool_call,
    render_write_tool_call,
)
from klaude_code.tui.components.tools._look_at import render_look_at_tool_call
from klaude_code.tui.components.tools._manage_shell import (
    extract_shell_task_ui_extra,
    render_manage_shell_result,
    render_manage_shell_tool_call,
    render_shell_completion,
)
from klaude_code.tui.components.tools._question import (
    render_ask_user_question_summary,
    render_ask_user_question_tool_call,
    render_ask_user_question_tool_result,
)
from klaude_code.tui.components.tools._read import render_read_preview, render_read_tool_call
from klaude_code.tui.components.tools._todo import render_todo, render_todo_message
from klaude_code.tui.components.tools._web import (
    extract_web_result_for_display,
    parse_web_search_results,
    render_web_fetch_tool_call,
    render_web_search_results,
    render_web_search_tool_call,
)
from klaude_code.tui.transcript_detail import Detail

if TYPE_CHECKING:
    from klaude_code.tui.components.background_tasks import TaskDirectory


def render_tool_call(
    e: events.ToolCallEvent,
    *,
    shell_task: ShellTaskSnapshot | None = None,
    task_directory: "TaskDirectory | None" = None,
) -> RenderableType | None:
    """Unified entry point for rendering tool calls.

    Returns a Rich Renderable or None if the tool call should not be rendered.
    """

    if is_sub_agent_tool(e.tool_name):
        return None

    if e.tool_name in {tools.MANAGE_TASKS, tools.LIST_PEERS, tools.MESSAGE_PEER}:
        from klaude_code.tui.components.background_tasks import render_collaboration_call

        return render_collaboration_call(e.tool_name, e.arguments, task_directory)

    match e.tool_name:
        case tools.READ:
            return render_read_tool_call(e.arguments)
        case tools.LOOK_AT:
            return render_look_at_tool_call(e.arguments)
        case tools.EDIT:
            return render_edit_tool_call(e.arguments)
        case tools.WRITE:
            return render_write_tool_call(e.arguments)
        case tools.BASH:
            return render_bash_tool_call(e.arguments)
        case tools.MANAGE_SHELL:
            return render_manage_shell_tool_call(e.arguments, shell_task=shell_task)
        case tools.APPLY_PATCH:
            return render_apply_patch_tool_call(e.arguments)
        case tools.TODO_WRITE:
            return None
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


def render_markdown_doc(
    md_ui: MarkdownDocUIExtra,
    *,
    code_theme: str,
    fold: bool = False,
    show_file_path: bool = False,
    indent: int = TOOL_RESULT_INDENT,
) -> RenderableType:
    """Render a Markdown document preview in the file-change panel."""
    title = render_path(md_ui.file_path, ThemeKey.TOOL_PARAM_FILE_PATH) if show_file_path else None
    if title is not None:
        title.no_wrap = True
        title.overflow = "ellipsis"

    if fold:
        lines = md_ui.content.splitlines()
        hidden_lines = max(0, len(lines) - r_diffs.FOLD_DOC_PREVIEW_LINES)
        preview: list[RenderableType] = [
            Text(line, style=ThemeKey.TOOL_RESULT, no_wrap=True, overflow="ellipsis")
            for line in lines[: r_diffs.FOLD_DOC_PREVIEW_LINES]
        ]
        if hidden_lines:
            preview.append(
                Text(
                    f"\u2026 {hidden_lines} more lines · {r_diffs.EXPAND_DIFFS_HINT}",
                    style=ThemeKey.TOOL_RESULT_TRUNCATED,
                )
            )
        return render_result_panel(Group(*preview), title=title, indent=indent)

    return render_result_panel(
        NoInsetMarkdown(md_ui.content, code_theme=code_theme, style=ThemeKey.TOOL_RESULT),
        title=title,
        indent=indent,
    )


def _file_change_count(ui_extra: ToolResultUIExtra | None) -> int:
    items = ui_extra.items if isinstance(ui_extra, MultiUIExtra) else [ui_extra]
    return sum(len(item.files) if isinstance(item, DiffUIExtra) else 1 for item in items if item is not None)


class FileChangeStat(BaseModel):
    path: str
    added: int = 0
    removed: int = 0


def file_change_stats(e: events.ToolResultEvent) -> list[FileChangeStat]:
    """Per-file line counts of a file tool's result, for summarizing a run's changes."""
    items = e.ui_extra.items if isinstance(e.ui_extra, MultiUIExtra) else [e.ui_extra]
    stats: list[FileChangeStat] = []
    for item in items:
        if isinstance(item, DiffUIExtra):
            stats.extend(
                FileChangeStat(path=file.file_path, added=file.stats_add, removed=file.stats_remove)
                for file in item.files
            )
        elif isinstance(item, MarkdownDocUIExtra):
            stats.append(FileChangeStat(path=item.file_path, added=len(item.content.splitlines())))
    return stats


def render_tool_result(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
    detail: Detail = Detail.COMPACT,
    max_lines: int = FULL_TOOL_RESULT_MAX_LINES,
    show_shell_task_identity: bool = False,
    task_action: str = "",
    task_directory: "TaskDirectory | None" = None,
    fold_diffs: bool = False,
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

    if e.tool_name == tools.MANAGE_TASKS:
        from klaude_code.tui.components.background_tasks import render_manage_tasks_result

        result = render_manage_tasks_result(
            e.result,
            detail=detail,
            action=task_action,
            directory=task_directory,
            max_lines=max_lines,
            status=e.status,
        )
        return pad_result(result) if result is not None else None

    # Handle error case
    if e.is_error and e.ui_extra is None:
        if e.tool_name == tools.TODO_WRITE:
            result = e.result if len(e.result.strip()) > 0 else "(no content)"
            return pad_result(render_todo_message(result, status=e.status))
        return pad_result(
            render_fallback_tool_result(
                e.tool_name,
                e.result,
                status=e.status,
                detail=detail,
                max_lines=max_lines,
            )
        )

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
                        fold=fold_diffs,
                        show_file_path=show_patch_file_names,
                    )
                )
            elif isinstance(item, DiffUIExtra):
                rendered.append(
                    render_result_panel(
                        r_diffs.render_structured_diff(
                            item,
                            show_file_name=show_patch_file_names,
                            fold=fold_diffs,
                        )
                    )
                )
        return Group(*rendered) if rendered else None

    diff_ui = _extract_diff(e.ui_extra)
    md_ui = _extract_markdown_doc(e.ui_extra)

    def _render_fallback() -> RenderableType:
        if len(e.result.strip()) == 0:
            return pad_result(
                render_fallback_tool_result(e.tool_name, "(no content)", detail=detail, max_lines=max_lines)
            )
        return pad_result(
            render_fallback_tool_result(
                e.tool_name,
                e.result,
                status=e.status,
                detail=detail,
                max_lines=max_lines,
            )
        )

    match e.tool_name:
        case tools.READ:
            if isinstance(e.ui_extra, ReadPreviewUIExtra):
                return pad_result(render_read_preview(e.ui_extra))
            return None
        case tools.EDIT:
            return render_result_panel(
                r_diffs.render_structured_diff(diff_ui, fold=fold_diffs) if diff_ui else Text("")
            )
        case tools.WRITE:
            if md_ui:
                # Markdown docs already include their own 2-character indent.
                return render_markdown_doc(md_ui, code_theme=code_theme, fold=fold_diffs)
            return render_result_panel(
                r_diffs.render_structured_diff(diff_ui, fold=fold_diffs) if diff_ui else Text("")
            )
        case tools.APPLY_PATCH:
            if md_ui:
                # Markdown docs already include their own 2-character indent.
                return render_markdown_doc(md_ui, code_theme=code_theme, fold=fold_diffs)
            if diff_ui:
                return render_result_panel(
                    r_diffs.render_structured_diff(
                        diff_ui,
                        show_file_name=len(diff_ui.files) > 1,
                        fold=fold_diffs,
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
        case tools.MANAGE_SHELL:
            shell_ui = extract_shell_task_ui_extra(e.ui_extra, e.result)
            if shell_ui is not None and detail.is_compact and shell_ui.action == "wait":
                finished = [task for task in shell_ui.tasks if task.status not in ACTIVE_TASK_STATUSES]
                if not finished:
                    return None
                if task_directory is not None:
                    finished = [task for task in finished if task_directory.claim_task(task.task_id)]
                if not finished:
                    return None
                # The automatic report and the wait share one claim, so whichever
                # observes the finish first prints the single completion row.
                return render_shell_completion(finished, detail=detail)
            if shell_ui is not None:
                return pad_result(
                    render_manage_shell_result(
                        shell_ui, detail=detail, max_lines=max_lines, show_task_identity=show_shell_task_identity
                    )
                )
            return _render_fallback()
        case tools.LIST_PEERS | tools.MESSAGE_PEER:
            from klaude_code.tui.components.background_tasks import (
                is_accepted_peer_receipt,
                render_collaboration_result,
            )

            if e.tool_name == tools.MESSAGE_PEER and detail.is_compact and is_accepted_peer_receipt(e.result):
                return None
            result = render_collaboration_result(
                e.tool_name, e.result, detail=detail, max_lines=max_lines, directory=task_directory
            )
            return pad_result(result) if result is not None else _render_fallback()
        case tools.WEB_SEARCH:
            search_results = parse_web_search_results(e.result)
            if search_results:
                rendered = render_result_panel(render_web_search_results(search_results, detail=detail))
            else:
                display_result = extract_web_result_for_display(e.result)
                rendered = pad_result(
                    render_fallback_tool_result(
                        e.tool_name,
                        display_result if display_result.strip() else "(no content)",
                        status=e.status,
                        detail=detail,
                        max_lines=max_lines,
                    )
                )
            if isinstance(e.ui_extra, WebSearchUIExtra):
                provider_label = {
                    "parallel": "Parallel Search",
                    "exa": "Exa Search",
                    "brave": "Brave Search",
                    "deepseek": "DeepSeek Search",
                    "openai": "OpenAI Search",
                }.get(e.ui_extra.provider, e.ui_extra.provider)
                return Group(
                    AdaptiveIndent(Text(f"via {provider_label}", ThemeKey.METADATA_DIM), TOOL_RESULT_INDENT),
                    rendered,
                )
            return rendered
        case tools.WEB_FETCH:
            display_result = extract_web_result_for_display(e.result)
            if len(display_result.strip()) == 0:
                return pad_result(
                    render_fallback_tool_result(e.tool_name, "(no content)", detail=detail, max_lines=max_lines)
                )
            return pad_result(
                render_fallback_tool_result(
                    e.tool_name,
                    display_result,
                    status=e.status,
                    detail=detail,
                    max_lines=max_lines,
                )
            )
        case tools.ASK_USER_QUESTION:
            if isinstance(e.ui_extra, AskUserQuestionSummaryUIExtra):
                return AdaptiveIndent(render_ask_user_question_summary(e.ui_extra), TOOL_RESULT_INDENT)
            if len(e.result.strip()) == 0:
                return pad_result(
                    render_fallback_tool_result(e.tool_name, "(no content)", detail=detail, max_lines=max_lines)
                )
            return pad_result(render_ask_user_question_tool_result(e.result, status=e.status))
        case _:
            return _render_fallback()


def render_compact_file_change(
    e: events.ToolResultEvent,
    *,
    code_theme: str = "monokai",
    fold: bool = True,
) -> RenderableType | None:
    """Render diffs and new Markdown documents from a compact sub-agent result.

    Folded, a sub-agent's change is reported by its action line alone: its own
    block summarizes the work, and every file's diff would bury that summary.
    """
    if fold:
        return None
    items = e.ui_extra.items if isinstance(e.ui_extra, MultiUIExtra) else [e.ui_extra]
    show_file_names = _file_change_count(e.ui_extra) > 1
    rendered: list[RenderableType] = []
    for item in items:
        # Flush with the sub-agent header: the block's gutter and the panel border
        # already mark the nesting, so an extra indent would be a third boundary.
        if isinstance(item, DiffUIExtra):
            rendered.append(
                render_result_panel(
                    r_diffs.render_structured_diff(item, show_file_name=show_file_names),
                    indent=0,
                )
            )
        elif e.tool_name in (tools.WRITE, tools.APPLY_PATCH) and isinstance(item, MarkdownDocUIExtra):
            rendered.append(render_markdown_doc(item, code_theme=code_theme, show_file_path=show_file_names, indent=0))
    if not rendered:
        return None
    return Group(*rendered)
