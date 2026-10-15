"""Task management inside the prompt's existing selector overlay."""

import asyncio
from collections.abc import Callable

from klaude_code.protocol.background_task import ACTIVE_TASK_STATUSES, BackgroundTaskSnapshot, TaskRequest
from klaude_code.tui.client.base import RuntimeClient
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput
from klaude_code.tui.terminal.selector import SelectItem


def _item(label: str, value: str) -> SelectItem[str]:
    return SelectItem(title=[("", label + "\n")], value=value, search_text=label)


def task_label(task: BackgroundTaskSnapshot) -> str:
    return " ".join((task.description or (task.shell.command if task.shell else "") or "Agent task").split())


class TaskPanel:
    def __init__(
        self, client: RuntimeClient, prompt: PromptToolkitInput, attention: Callable[[], dict[str, str]]
    ) -> None:
        self.client = client
        self.prompt = prompt
        self.attention = attention
        self._open = False
        self._task: asyncio.Task[None] | None = None

    def close(self) -> None:
        self.prompt.close_task_overlay()
        if self._task is not None:
            self._task.cancel()

    async def open(self) -> None:
        if self._open:
            return
        self._open = True
        self._task = asyncio.current_task()
        try:
            await self._list()
        finally:
            self._open = False
            self._task = None

    async def _list(self) -> None:
        notice = "Tasks · ↑/↓ Enter · Esc closes"
        while True:
            try:
                response = await self.client.manage_tasks(TaskRequest(action="list"))
            except Exception as exc:
                await self.prompt.choose_task_action(f"Tasks failed: {exc}", [_item("Close", "close")])
                return
            attention = self.attention()
            tasks = sorted(
                response.tasks,
                key=lambda task: (
                    0
                    if task.ref.session_id in attention
                    else 1
                    if task.status in {"failed", "lost", "timed_out"}
                    else 2
                    if task.status in ACTIVE_TASK_STATUSES
                    else 3,
                    -task.started_at,
                ),
            )
            items = [
                _item(
                    f"{'Agent' if task.ref.kind == 'agent' else 'Bash'} · {attention.get(task.ref.session_id or '', task.status)} · {task_label(task)}",
                    task.ref.task_id,
                )
                for task in tasks
            ]
            items.append(_item("Refresh snapshot", "refresh"))
            selected = await self.prompt.choose_task_action(notice if tasks else "No background tasks", items)
            if selected is None:
                return
            if selected == "refresh":
                continue
            task = next((task for task in tasks if task.ref.task_id == selected), None)
            if task is not None:
                await self._detail(task)

    async def _detail(self, task: BackgroundTaskSnapshot) -> None:
        notice = ""
        while True:
            items = [_item("View output", "output"), _item("Refresh task", "refresh")]
            if task.status in ACTIVE_TASK_STATUSES:
                items.append(_item("Stop this task", "stop"))
            if task.ref.kind == "agent" and task.ref.session_id and task.status == "running":
                items.append(_item("Message this agent (external peer data)", "message"))
            items.extend(
                [_item(f"Task ID: {task.ref.task_id}", "id"), _item(f"Owner: {task.ref.owner_session_id}", "id")]
            )
            if task.ref.session_id:
                items.append(_item(f"Child session: {task.ref.session_id}", "id"))
            items.append(_item("Back to tasks", "back"))
            status = self.attention().get(task.ref.session_id or "", task.status)
            action = await self.prompt.choose_task_action(
                notice or f"{task_label(task)} · {task.ref.kind} · {status}", items
            )
            if action is None or action == "back":
                return
            try:
                if action == "output":
                    await self._output(task)
                elif action == "message":
                    notice = await self._message(task)
                elif action in {"stop", "refresh"}:
                    response = await self.client.manage_tasks(
                        TaskRequest(
                            action="stop" if action == "stop" else "list",
                            task_id=task.ref.task_id if action == "stop" else None,
                        )
                    )
                    updated = next((item for item in response.tasks if item.ref.task_id == task.ref.task_id), None)
                    if updated is None:
                        notice = "Task no longer available"
                    else:
                        task = updated
                        notice = f"Server reports: {task.status}"
            except Exception as exc:
                notice = f"{action} failed: {exc}"

    async def _output(self, task: BackgroundTaskSnapshot) -> None:
        offsets = [0]
        while True:
            response = await self.client.manage_tasks(
                TaskRequest(action="output", task_id=task.ref.task_id, offset=offsets[-1], limit=4096)
            )
            items = [_item("Back to task", "back")]
            if response.truncated:
                items.append(_item("Next page", "next"))
            if len(offsets) > 1:
                items.append(_item("Previous page", "previous"))
            output = (
                "Output expired or unavailable" if response.output_unavailable else response.output or "No output yet"
            )
            items.extend(_item(line, "line") for line in output.splitlines())
            selected = await self.prompt.choose_task_action(f"{task_label(task)} · output offset {offsets[-1]}", items)
            if selected is None or selected == "back":
                return
            if selected == "next":
                offsets.append(response.next_offset)
            elif selected == "previous":
                offsets.pop()

    async def _message(self, task: BackgroundTaskSnapshot) -> str:
        body = await self.prompt.choose_task_action(
            f"Message → {task_label(task)} (not main)", [_item("Review message", "review")], text_entry=True
        )
        if body is None or not body.strip():
            return "Message not sent"
        confirmation = await self.prompt.choose_task_action(
            f"Send peer data → {task.ref.session_id}?", [_item("Cancel", "cancel"), _item(f"Send: {body}", "send")]
        )
        if confirmation != "send":
            return "Message not sent"
        receipt = await self.client.send_task_message(task.ref.task_id, body)
        return f"{'Queued' if receipt.accepted else 'Not accepted'} → {receipt.target} (transport receipt, not read)"
