from collections.abc import Iterable

from pydantic import BaseModel, ValidationError
from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text

from klaude_code.protocol import events, tools
from klaude_code.protocol.background_task import ACTIVE_TASK_STATUSES, BackgroundTaskSnapshot, TaskResponse
from klaude_code.protocol.peer import PeerInfo, PeerReceipt
from klaude_code.tui.components.common import format_pascal_case, truncate_middle_lines
from klaude_code.tui.components.rich.clip import MaxLines
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools._common import (
    MARK_CALLBACK,
    MARK_PLAN,
    TOOL_GROUP_INDENT,
    TOOL_RESULT_INDENT,
    TOOL_SUBJECT_INDENT,
    AdaptiveIndent,
    ToolResultStatus,
    render_result_panel,
    render_tool_call_tree,
)
from klaude_code.tui.components.tools._manage_shell import render_shell_callback
from klaude_code.tui.components.tools._presentation import get_tool_call_presentation, one_line, parse_tool_arguments
from klaude_code.tui.transcript_detail import Detail

MARK_MESSAGE = "✉"
_FAILURE_STATUSES = frozenset({"failed", "timed_out", "lost"})


class PeerList(BaseModel):
    peers: list[PeerInfo]


class TaskDirectory:
    """Human labels for task and session IDs, fed by the renderer's task snapshots.

    The transcript names tasks and peers by what they do; IDs stay in `/tasks`
    and the expanded view.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, BackgroundTaskSnapshot] = {}
        self._session_labels: dict[str, str] = {}
        # Finished tasks already printed, so a report and a wait result for the
        # same finish do not both reach the transcript.
        self._reported: set[str] = set()
        self._reported_sessions: set[str] = set()
        # Child sessions whose `▌` batch block already printed their result.
        self._summarized_sessions: set[str] = set()

    def reset(self) -> None:
        """Forget what was printed; keep the labels.

        A rebuild replays the tape's single, latest task snapshot after the
        tool calls that name those tasks, so labels must outlive the repaint.
        """
        self._reported.clear()
        self._reported_sessions.clear()
        self._summarized_sessions.clear()

    def update(self, tasks: Iterable[BackgroundTaskSnapshot]) -> None:
        for task in tasks:
            self._tasks[task.ref.task_id] = task
            if task.ref.session_id and task.description:
                self._session_labels[task.ref.session_id] = one_line(task.description)

    def name_session(self, session_id: str, label: str) -> None:
        if label.strip():
            self._session_labels[session_id] = one_line(label)

    def task(self, task_id: object) -> BackgroundTaskSnapshot | None:
        if not isinstance(task_id, str) or not task_id:
            return None
        if task_id in self._tasks:
            return self._tasks[task_id]
        matches = [task for key, task in self._tasks.items() if key.startswith(task_id)]
        return matches[0] if len(matches) == 1 else None

    def task_label(self, task_id: object) -> str:
        task = self.task(task_id)
        if task is not None:
            return task_label(task)
        # An unknown ID means nothing to a reader; say what kind of thing it is.
        return "a background task" if isinstance(task_id, str) and task_id else "background tasks"

    def session_label(self, session_id: str | None, fallback: str) -> str:
        if session_id and session_id in self._session_labels:
            return self._session_labels[session_id]
        label = one_line(fallback)
        # A bare session ID carries no meaning to a reader.
        return "another agent" if not label or _looks_like_id(label) else label

    def claim_summary(self, session_id: str) -> bool:
        """Whether a child's batch block may print: its task was not reported another way."""
        if session_id in self._reported_sessions:
            return False
        self._summarized_sessions.add(session_id)
        return True

    def claim_task(self, task_id: str) -> bool:
        """Whether this finished task still needs its one transcript row."""
        if task_id in self._reported:
            return False
        self._reported.add(task_id)
        return True

    def claim_report(self, task: BackgroundTaskSnapshot) -> bool:
        """Whether this finished task still needs its one transcript report."""
        if task.ref.session_id in self._summarized_sessions or not self.claim_task(task.ref.task_id):
            return False
        if task.ref.session_id:
            self._reported_sessions.add(task.ref.session_id)
        return True


def _looks_like_id(value: str) -> bool:
    compact = value.replace("-", "")
    return len(compact) >= 8 and all(char in "0123456789abcdef" for char in compact.lower())


def parse_task_response(text: str) -> TaskResponse | None:
    lines = text.splitlines()
    while lines and (lines[0].startswith("source=") or lines[0].startswith("interrupted-wait")):
        lines.pop(0)
    try:
        return TaskResponse.model_validate_json("\n".join(lines))
    except ValidationError:
        return None


def task_label(task: BackgroundTaskSnapshot) -> str:
    label = task.description or (task.shell.description or task.shell.command if task.shell else "")
    return one_line(label) or ("Agent task" if task.ref.kind == "agent" else "Bash task")


def _status_style(task: BackgroundTaskSnapshot) -> ThemeKey:
    exit_code = task.shell.exit_code if task.shell is not None else None
    if task.status in _FAILURE_STATUSES or (task.status == "completed" and exit_code not in (None, 0)):
        return ThemeKey.ERROR
    if task.status == "completed":
        return ThemeKey.METADATA_GREEN_DIM
    if task.status == "stopped":
        return ThemeKey.INTERRUPT
    if task.status in {"running", "stopping"}:
        return ThemeKey.WARN
    return ThemeKey.METADATA_DIM


def _status_text(task: BackgroundTaskSnapshot) -> Text:
    style = _status_style(task)
    text = Text(task.status, style=style)
    if task.shell is not None and task.shell.exit_code is not None:
        text.append(f" · exit {task.shell.exit_code}", style=style)
    return text


def render_task_response(
    response: TaskResponse, *, detail: Detail, show_output: bool = True, max_lines: int | None = None
) -> RenderableType:
    rows: list[RenderableType] = []
    limit = 8 if detail.is_compact else len(response.tasks)
    if max_lines is not None:
        limit = min(limit, max(1, max_lines))
    tasks = sorted(
        response.tasks,
        key=lambda task: 0 if task.status in _FAILURE_STATUSES else 1 if task.status in ACTIVE_TASK_STATUSES else 2,
    )
    selected = tasks[:limit]
    task_rows = Table.grid(padding=(0, 2), expand=True)
    task_rows.add_column(ratio=1, overflow="ellipsis", no_wrap=detail.is_compact)
    task_rows.add_column(justify="right", no_wrap=True)
    for task in selected:
        name = Text(task_label(task), style=ThemeKey.TOOL_RESULT)
        state = Text(f"{'Agent' if task.ref.kind == 'agent' else 'Bash'} · ", style=ThemeKey.METADATA_DIM)
        state.append_text(_status_text(task))
        task_rows.add_row(name, state)
        if not detail.is_compact:
            identity = Text(f"id: {task.ref.task_id}", style=ThemeKey.METADATA_DIM)
            if task.ref.session_id:
                identity.append(f" · session: {task.ref.session_id}")
            task_rows.add_row(identity, Text(""))
            if task.shell is not None:
                task_rows.add_row(Text(f"log: {task.shell.output_path}", style=ThemeKey.METADATA_DIM), Text(""))
    if selected:
        rows.append(task_rows)
    if not response.tasks:
        rows.append(Text("No background tasks.", style=ThemeKey.METADATA_DIM))
    if len(selected) < len(response.tasks):
        rows.append(
            Text(f"… {len(response.tasks) - len(selected)} more tasks · /tasks", style=ThemeKey.TOOL_RESULT_TRUNCATED)
        )
    if response.interrupted_wait and not detail.is_compact:
        rows.append(Text("Wait interrupted; no task was stopped.", style=ThemeKey.WARN))
    if response.output_unavailable:
        rows.append(Text("Output expired or unavailable.", style=ThemeKey.ERROR))
    elif response.output and show_output:
        lines = response.output.splitlines()
        visible = response.output[:2000].splitlines()[:8] if detail.is_compact else lines
        output = (
            truncate_middle_lines("\n".join(visible), max_lines=max(1, max_lines))
            if max_lines is not None
            else Text("\n".join(visible), style=ThemeKey.TOOL_RESULT)
        )
        output.no_wrap = detail.is_compact
        output.overflow = "ellipsis" if detail.is_compact else "fold"
        rows.append(output)
        if len(visible) < len(lines) or (detail.is_compact and len(response.output) > 2000):
            rows.append(Text("… full page: ctrl-o", style=ThemeKey.TOOL_RESULT_TRUNCATED))
    if response.truncated:
        task_id = response.tasks[0].ref.task_id if response.tasks else "TASK_ID"
        rows.append(Text(f"More output: /tasks output {task_id} {response.next_offset}", style=ThemeKey.METADATA_DIM))
    return Group(*rows)


def render_task_outcome(task: BackgroundTaskSnapshot) -> RenderableType:
    """One report row for a finished Bash task: `› Shell  <what it did>  <status>`."""
    if task.shell is not None:
        return render_shell_callback(task.shell)
    details = Text(task_label(task), style=ThemeKey.BASH_TOOL_DESCRIPTION)
    details.append(" · ")
    details.append_text(_status_text(task))
    return render_tool_call_tree(mark=MARK_CALLBACK, tool_name="Shell", details=details)


def unreported_finished_tasks(response: TaskResponse, directory: TaskDirectory) -> list[BackgroundTaskSnapshot]:
    """Finished tasks in `response` the transcript has not reported yet.

    Running tasks belong to the status bar, and an agent whose batch block
    already printed is not reported again.
    """
    return [task for task in response.tasks if task.status not in ACTIVE_TASK_STATUSES and directory.claim_report(task)]


def render_task_outcomes(response: TaskResponse, directory: TaskDirectory) -> RenderableType | None:
    """Compact transcript lines for newly finished Bash tasks."""
    rows = [
        render_task_outcome(task) for task in unreported_finished_tasks(response, directory) if task.ref.kind == "shell"
    ]
    return Group(*rows) if rows else None


def render_manage_tasks_call(arguments: str, directory: TaskDirectory) -> RenderableType:
    args = parse_tool_arguments(arguments)
    action = one_line(args.get("action", ""))
    task_id = args.get("task_id")
    label = directory.task_label(task_id)
    subject = Text(overflow="ellipsis", no_wrap=True)
    if action == "wait":
        subject.append("Waiting for ", style=ThemeKey.TOOL_PARAM)
        subject.append(label, style=ThemeKey.BASH_TOOL_DESCRIPTION)
    elif action in {"output", "stop"} and task_id:
        subject.append(action.title(), style=ThemeKey.TOOL_PARAM)
        subject.append(f" {label}", style=ThemeKey.BASH_TOOL_DESCRIPTION)
    else:
        subject.append(action.title() or "List", style=ThemeKey.TOOL_PARAM)
    return render_tool_call_tree(mark=MARK_PLAN, tool_name="Tasks", details=subject)


def render_manage_tasks_result(
    result: str,
    *,
    detail: Detail,
    action: str = "",
    directory: TaskDirectory | None = None,
    max_lines: int | None = None,
    status: ToolResultStatus = "success",
) -> RenderableType | None:
    response = parse_task_response(result)
    if status == "success" and response is not None:
        if directory is not None:
            directory.update(response.tasks)
        if detail.is_compact and action != "list":
            return render_task_outcomes(response, directory or TaskDirectory())
        return render_task_response(response, detail=detail, max_lines=max_lines)
    style = ThemeKey.INTERRUPT if status == "aborted" else ThemeKey.ERROR
    heading = "Task control interrupted" if status == "aborted" else "Task control failed"
    if status == "success":
        heading = "Task response could not be read"
    limit = min(8, max(1, max_lines or 8)) if detail.is_compact else max(1, max_lines or 10)
    body = truncate_middle_lines(result or "No result details.", max_lines=limit, base_style=style)
    body.no_wrap = detail.is_compact
    body.overflow = "ellipsis" if detail.is_compact else "fold"
    return Group(Text(heading, style=style), body)


def render_task_control(event: events.TaskControlResultEvent, *, detail: Detail) -> RenderableType:
    if event.error is not None:
        return Text(f"Tasks {event.request.action} failed: {event.error}", style=ThemeKey.ERROR)
    if event.response is None:
        return Text("Task control returned no result.", style=ThemeKey.ERROR)
    return render_task_response(event.response, detail=detail)


_COMPACT_MESSAGE_MAX_LINES = 6


def render_message(mark: str, verb: str, peer: str, body: str, *, detail: Detail) -> RenderableType:
    """A message between agents: a tool-style header naming the peer, the body in a panel.

    Direction shows twice: the mark (`✉` sent, `›` filled back in) and one
    color for mark, border, and body (blue sent, purple received). Compact
    mode shows the first lines; ctrl-o shows it all.
    """
    color = ThemeKey.PEER_MESSAGE_SENT if mark == MARK_MESSAGE else ThemeKey.PEER_MESSAGE_RECEIVED
    header = Text(overflow="ellipsis", no_wrap=True)
    header.append(f"{verb} ", style=ThemeKey.METADATA)
    header.append(peer, style=ThemeKey.TOOL_PARAM)
    lines = body.strip().splitlines() or [""]
    shown = lines[:_COMPACT_MESSAGE_MAX_LINES] if detail.is_compact else lines
    text: RenderableType = Text("\n".join(shown), style=color, overflow="fold")
    if detail.is_compact:
        # Long lines wrap too; the cap counts rows on screen, not source lines.
        text = MaxLines(text, _COMPACT_MESSAGE_MAX_LINES, ellipsis_style=ThemeKey.TOOL_RESULT_TRUNCATED)
    content: list[RenderableType] = [text]
    if len(shown) < len(lines):
        content.append(Text(f"… {len(lines) - len(shown)} more lines · ctrl-o", style=ThemeKey.TOOL_RESULT_TRUNCATED))
    return Group(
        render_tool_call_tree(mark=mark, tool_name="Message", details=header, mark_style=color),
        render_result_panel(Group(*content), border_style=color),
    )


def render_peer_message(event: events.UserMessageEvent, *, detail: Detail, directory: TaskDirectory) -> RenderableType:
    peer = event.peer_message
    if peer is None:
        return Text("Peer message metadata unavailable.", style=ThemeKey.METADATA_DIM)
    sender = directory.session_label(peer.sender_session_id, peer.sender_label)
    row = render_message(MARK_CALLBACK, "from", sender, peer.body, detail=detail)
    if detail.is_compact:
        return row
    meta = Text(
        f"sender: {peer.sender_session_id or peer.sender_label} · recipient: {peer.recipient}\n"
        f"id: {peer.id} · reply_to: {peer.reply_to or '-'}",
        style=ThemeKey.METADATA_DIM,
        overflow="fold",
    )
    return Group(row, AdaptiveIndent(meta, TOOL_RESULT_INDENT))


def render_sourced_message(
    event: events.UserMessageEvent, *, detail: Detail, directory: TaskDirectory | None = None
) -> RenderableType | None:
    directory = directory or TaskDirectory()
    if event.source == "peer_message":
        return render_peer_message(event, detail=detail, directory=directory)
    response = parse_task_response(event.content)
    if detail.is_compact:
        # Compact task reports go through `TUICommandRenderer`, which owns the batch blocks.
        return render_task_outcomes(response, directory) if response is not None else None
    # The body's task rows name each task and its status; the heading only marks the report.
    heading = Text("Background report", style=ThemeKey.METADATA)
    if response is None:
        return _report_row(heading, Text("Result: /tasks output TASK_ID", style=ThemeKey.METADATA_DIM))
    if response.truncated or len(response.output) > 8192:
        task_id = response.tasks[0].ref.task_id if response.tasks else "TASK_ID"
        body: RenderableType = Group(
            render_task_response(response, detail=detail, show_output=False),
            Text(f"Result: /tasks output {task_id}", style=ThemeKey.METADATA_DIM),
        )
    else:
        body = render_task_response(response, detail=detail)
    return _report_row(heading, body)


def _report_row(heading: Text, body: RenderableType) -> RenderableType:
    """A background report as a callback row, its body aligned under the subject column."""
    row = render_tool_call_tree(mark=MARK_CALLBACK, tool_name="Task", details=heading, overflow="fold")
    return Group(row, AdaptiveIndent(body, TOOL_SUBJECT_INDENT))


def render_collaboration_result(
    tool_name: str,
    result: str,
    *,
    detail: Detail,
    max_lines: int | None = None,
    directory: TaskDirectory | None = None,
) -> RenderableType | None:
    try:
        if tool_name == tools.MANAGE_TASKS:
            return render_manage_tasks_result(result, detail=detail, action="list", max_lines=max_lines)
        if tool_name == tools.LIST_PEERS:
            peers = PeerList.model_validate_json(result).peers
            if directory is not None:
                for peer in peers:
                    directory.name_session(peer.session_id, peer.name or peer.description)
            selected = peers[:8] if detail.is_compact else peers
            lines = [
                " · ".join(part for part in (peer.name or "unnamed agent", peer.state, peer.description) if part)
                for peer in selected
            ]
            if len(selected) < len(peers):
                lines.append(f"… {len(peers) - len(selected)} more peers · ctrl-o")
            return Text("\n".join(lines) or "No active peers.", style=ThemeKey.TOOL_RESULT, overflow="fold")
        if tool_name == tools.MESSAGE_PEER:
            receipt = PeerReceipt.model_validate_json(result)
            return Text(
                f"{'queued' if receipt.accepted else 'not accepted'} · id: {receipt.message_id} "
                "(transport receipt, not read)",
                style=ThemeKey.METADATA_DIM if receipt.accepted else ThemeKey.ERROR,
            )
    except ValidationError:
        return None
    return None


def is_accepted_peer_receipt(result: str) -> bool:
    """Delivery is the expected outcome of MessagePeer; compact mode prints only refusals."""
    try:
        return PeerReceipt.model_validate_json(result).accepted
    except ValidationError:
        return False


def render_collaboration_call(
    tool_name: str, arguments: str, directory: TaskDirectory | None = None, *, detail: Detail = Detail.COMPACT
) -> RenderableType:
    directory = directory or TaskDirectory()
    if tool_name == tools.MANAGE_TASKS:
        return render_manage_tasks_call(arguments, directory)
    if tool_name == tools.MESSAGE_PEER:
        args = parse_tool_arguments(arguments)
        target = directory.session_label(str(args.get("target", "")), str(args.get("target", "")))
        return render_message(MARK_MESSAGE, "to", target, str(args.get("body", "")), detail=detail)
    presentation = get_tool_call_presentation(tool_name, arguments)
    return render_tool_call_tree(
        mark=MARK_PLAN,
        tool_name=presentation.name,
        details=Text(presentation.subject, style=ThemeKey.TOOL_PARAM),
    )


def render_agent_launch(arguments: str, *, first: bool) -> RenderableType:
    """Rows for background agent launches; consecutive launches share one header."""
    args = parse_tool_arguments(arguments)
    agent_type = format_pascal_case(one_line(args.get("type", "")) or "general-purpose")
    row = Text(no_wrap=True, overflow="ellipsis")
    row.append(" " * (TOOL_GROUP_INDENT + 2))
    row.append("↳ ", style=ThemeKey.TOOL_RESULT_TREE_PREFIX)
    row.append(agent_type, style=ThemeKey.TOOL_NAME)
    if description := one_line(args.get("description", "")):
        row.append(f": {description}", style=ThemeKey.TOOL_PARAM)
    if not first:
        return row
    header = render_tool_call_tree(
        mark=MARK_PLAN, tool_name="Agents", details=Text("running in background", style=ThemeKey.METADATA_DIM)
    )
    return Group(header, row)
