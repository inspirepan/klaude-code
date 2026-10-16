import json
from typing import cast

from pydantic import TypeAdapter
from rich.cells import cell_len, set_cell_size
from rich.console import Console, ConsoleOptions, Group, RenderableType, RenderResult
from rich.measure import Measurement
from rich.text import Text

from klaude_code.protocol.models import ShellTaskUIExtra, ToolResultUIExtra
from klaude_code.protocol.shell_task import ShellTaskOutput, ShellTaskSnapshot
from klaude_code.tui.components.common import truncate_middle_lines
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    FULL_TOOL_RESULT_MAX_LINES,
    MARK_BASH,
    MARK_CALLBACK,
    MIN_INDENTED_CONTENT_WIDTH,
    TOOL_RESULT_INDENT,
    TOOL_SUBJECT_INDENT,
    AdaptiveIndent,
    render_tool_call_tree,
)
from klaude_code.tui.components.tools._presentation import one_line, parse_tool_arguments
from klaude_code.tui.transcript_detail import Detail

_COMPACT_MAX_LINES = 5
_LEGACY_MAX_CHARS = 2 * 1024 * 1024
_FAILURE_STATUSES = {"failed", "timed_out", "lost"}


def render_manage_shell_subject(arguments: str, *, shell_task: ShellTaskSnapshot | None = None) -> Text:
    args = parse_tool_arguments(arguments)
    action = one_line(args.get("action", "")).title()
    line = Text(overflow="fold")
    line.append("Waiting for" if action == "Wait" else action, style=ThemeKey.TOOL_PARAM)
    if action != "List":
        task_id = args.get("task_id")
        description = ""
        if shell_task is not None:
            description = one_line(shell_task.description) or one_line(shell_task.command)
            if description:
                line.append(" ")
                line.append(description, style=ThemeKey.BASH_TOOL_DESCRIPTION)
            task_id = shell_task.task_id
        # The ID only stands in for a task the reader cannot otherwise name.
        if not description and isinstance(task_id, str) and task_id:
            line.append(f" {task_id[:8]}", style=ThemeKey.METADATA_DIM)
    wait_ms = args.get("wait_ms")
    if action == "Wait" and isinstance(wait_ms, int) and not isinstance(wait_ms, bool) and wait_ms != 10000:
        line.append(f" · {wait_ms / 1000:g}s", style=ThemeKey.METADATA_DIM)
    offset = args.get("offset")
    if action == "Output" and isinstance(offset, int) and not isinstance(offset, bool) and offset != 0:
        line.append(f" · offset {offset}", style=ThemeKey.METADATA_DIM)
    return line


def render_manage_shell_tool_call(arguments: str, *, shell_task: ShellTaskSnapshot | None = None) -> RenderableType:
    return ManageShellRow(render_manage_shell_subject(arguments, shell_task=shell_task))


class ManageShellRow:
    def __init__(self, subject: RenderableType, *, mark: str = MARK_BASH) -> None:
        self.subject = subject
        self.mark = mark

    def _renderable(self, width: int) -> RenderableType:
        narrow = width < TOOL_SUBJECT_INDENT + MIN_INDENTED_CONTENT_WIDTH
        row = render_tool_call_tree(
            mark=self.mark, tool_name="Shell", details=None if narrow else self.subject, overflow="fold"
        )
        return Group(row, AdaptiveIndent(self.subject, TOOL_RESULT_INDENT)) if narrow else row

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._renderable(options.max_width), options)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self._renderable(options.max_width))


_CALLBACK_SUBJECT_MAX_LINES = 2


class _ClippedSubject:
    """`what` then `status` on at most a few lines: a long command is cut, the status never is."""

    def __init__(self, what: Text, status: Text, max_lines: int = _CALLBACK_SUBJECT_MAX_LINES) -> None:
        self.what = what
        self.status = status
        self.max_lines = max_lines

    def _line(self, width: int) -> Text:
        what = self.what.copy()
        # Word wrapping wastes some of each row, so leave slack beyond the status.
        budget = max(8, width * self.max_lines - cell_len(self.status.plain) - width // 4)
        if cell_len(what.plain) > budget:
            what = Text(set_cell_size(what.plain, budget - 1) + "…", style=what.style)
        line = Text(overflow="fold")
        line.append_text(what)
        line.append_text(self.status)
        return line

    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        yield from console.render(self._line(options.max_width), options)

    def __rich_measure__(self, console: Console, options: ConsoleOptions) -> Measurement:
        return Measurement.get(console, options, self._line(options.max_width))


def render_shell_callback(task: ShellTaskSnapshot) -> RenderableType:
    """A finished background shell reported back by the system: `› Shell  <what it did>  <status>`."""
    description = one_line(task.description)
    what = Text(description or one_line(task.command), style=ThemeKey.BASH_TOOL_DESCRIPTION)
    status = Text(" · ", style=_task_status_style(task))
    status.append_text(_render_task(task, show_identity=False))
    return ManageShellRow(_ClippedSubject(what, status), mark=MARK_CALLBACK)


def extract_shell_task_ui_extra(ui_extra: ToolResultUIExtra | None, result: str) -> ShellTaskUIExtra | None:
    if isinstance(ui_extra, ShellTaskUIExtra):
        return ui_extra
    if ui_extra is not None or len(result) > _LEGACY_MAX_CHARS:
        return None
    # Only old persisted JSON needs decoding; new results use ui_extra.
    if not result.lstrip().startswith(("{", "[")):
        return None
    try:
        value: object = json.loads(result)
        if isinstance(value, list):
            tasks = TypeAdapter(list[ShellTaskSnapshot]).validate_python(value)
            return ShellTaskUIExtra(action="list", tasks=tasks)
        if not isinstance(value, dict):
            return None
        payload = cast(dict[str, object], value)
        if "task" in payload:
            page = ShellTaskOutput.model_validate(payload)
            return ShellTaskUIExtra(
                action="output",
                tasks=[page.task],
                output=page.output,
                next_offset=page.next_offset,
                truncated=page.truncated,
            )
        task = ShellTaskSnapshot.model_validate(payload)
        return ShellTaskUIExtra(action="wait", tasks=[task])
    except (ValueError, RecursionError):
        return None


def _task_status_style(task: ShellTaskSnapshot) -> ThemeKey:
    if task.status in _FAILURE_STATUSES or (task.status == "completed" and task.exit_code not in (None, 0)):
        return ThemeKey.ERROR
    if task.status == "completed":
        return ThemeKey.METADATA_GREEN_DIM
    if task.status in ("running", "stopping"):
        return ThemeKey.WARN
    return ThemeKey.METADATA_DIM


def _render_task(task: ShellTaskSnapshot, *, full_id: bool = False, show_identity: bool = True) -> Text:
    line = Text(overflow="fold")
    if show_identity:
        description = one_line(task.description) or one_line(task.command)
        if description:
            line.append(description, style=ThemeKey.BASH_TOOL_DESCRIPTION)
        if full_id or not description:
            if description:
                line.append(" ")
            line.append(task.task_id if full_id else task.task_id[:8], style=ThemeKey.METADATA_DIM)
    style = _task_status_style(task)
    line.append(f" · {task.status}" if show_identity else task.status, style=style)
    if task.exit_code is not None:
        line.append(f" · exit {task.exit_code}", style=style)
    if task.reason:
        line.append(f" · {one_line(task.reason)}", style=style)
    if task.output_expired:
        line.append(" · output expired", style=ThemeKey.WARN)
    return line


def _select_tasks(tasks: list[ShellTaskSnapshot], limit: int) -> tuple[list[ShellTaskSnapshot], Text | None]:
    """Up to `limit` tasks in their order, keeping failures visible past the preview."""
    priority = {idx for idx, task in enumerate(tasks) if _task_status_style(task) == ThemeKey.ERROR}
    chosen = set((sorted(priority) + [idx for idx in range(len(tasks)) if idx not in priority])[:limit])
    selected = [task for idx, task in enumerate(tasks) if idx in chosen]
    if len(tasks) == len(selected):
        return selected, None
    hidden_failures = sum(idx not in chosen for idx in priority)
    suffix = f", {hidden_failures} failures" if hidden_failures else ""
    return selected, Text(
        f"\u2026 (more {len(tasks) - len(selected)} tasks{suffix})", style=ThemeKey.TOOL_RESULT_TRUNCATED
    )


def render_manage_shell_result(
    ui_extra: ShellTaskUIExtra,
    *,
    detail: Detail = Detail.COMPACT,
    max_lines: int = FULL_TOOL_RESULT_MAX_LINES,
    show_task_identity: bool = False,
) -> RenderableType:
    limit = _COMPACT_MAX_LINES if detail.is_compact else max(1, max_lines)
    tasks = ui_extra.tasks
    show_task_identity = show_task_identity or ui_extra.action == "list" or len(tasks) != 1
    sections: list[RenderableType] = []
    if not tasks:
        sections.append(Text("No managed shell tasks.", style=ThemeKey.METADATA_DIM))
    else:
        selected, more = _select_tasks(tasks, limit)
        sections.extend(
            _render_task(task, full_id=not detail.is_compact, show_identity=show_task_identity) for task in selected
        )
        if more is not None:
            sections.append(more)
        if show_task_identity and not detail.is_compact and len(tasks) == 1 and tasks[0].description.strip():
            sections.append(Text(tasks[0].command, style=ThemeKey.BASH_ARGUMENT, overflow="fold"))
    if ui_extra.output is not None and not detail.is_compact:
        if ui_extra.output == "":
            sections.append(Text("(no output)", style=ThemeKey.METADATA_DIM))
        else:
            output = truncate_middle_lines(ui_extra.output, max_lines=limit, base_style=ThemeKey.TOOL_RESULT)
            # A final newline belongs to Console, not Text (Rich 14/15 compatibility).
            if output.plain.endswith("\n"):
                output = output[:-1]
            sections.append(output)
    if ui_extra.next_offset is not None or ui_extra.truncated:
        page_hint = f"next_offset {ui_extra.next_offset}" if ui_extra.next_offset is not None else ""
        if ui_extra.truncated:
            page_hint += " · has_more" if page_hint else "has_more"
        sections.append(Text(page_hint, style=ThemeKey.METADATA_DIM, overflow="fold"))
    return Group(*sections)


def is_pending_shell_wait(ui_extra: ShellTaskUIExtra) -> bool:
    """A wait that returned with every task still running: the status bar already says so."""
    return (
        ui_extra.action == "wait"
        and bool(ui_extra.tasks)
        and all(task.status in ("running", "stopping") for task in ui_extra.tasks)
    )


def render_shell_completion(
    tasks: list[ShellTaskSnapshot] | None,
    *,
    detail: Detail = Detail.COMPACT,
) -> RenderableType:
    if detail.is_compact and tasks:
        # One `› Shell` row per finished task: the call's shape, marked as a report.
        selected, more = _select_tasks(tasks, _COMPACT_MAX_LINES)
        rows: list[RenderableType] = [render_shell_callback(task) for task in selected]
        if more is not None:
            rows.append(AdaptiveIndent(more, TOOL_SUBJECT_INDENT))
        return Group(*rows)
    header = ManageShellRow(Text("Background results", style=ThemeKey.METADATA_DIM), mark=MARK_CALLBACK)
    if not tasks:
        result: RenderableType = Text("Task details unavailable.", style=ThemeKey.METADATA_DIM)
    else:
        result = render_manage_shell_result(ShellTaskUIExtra(action="list", tasks=tasks), detail=detail)
    return Group(header, AdaptiveIndent(result, TOOL_SUBJECT_INDENT))
