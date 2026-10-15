from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
from functools import partial
from typing import Any, cast

import pytest
from prompt_toolkit import PromptSession
from prompt_toolkit.document import Document
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from klaude_code.protocol.background_task import TaskRequest, TaskResponse
from klaude_code.protocol.message import UserInputPayload
from klaude_code.protocol.peer import PeerReceipt
from klaude_code.tui.client import server_api
from klaude_code.tui.client.base import RuntimeClient
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.input import prompt_toolkit as prompt_module
from klaude_code.tui.input.prompt_toolkit import PromptToolkitInput
from klaude_code.tui.task_panel import TaskPanel, _item

from .test_shared_tasks import task_snapshot


async def until(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.mark.parametrize(("columns", "rows"), [(80, 24), (60, 20)])
def test_busy_overlay_escape_preserves_live_draft_and_cursor_and_yields_to_approval(
    monkeypatch: pytest.MonkeyPatch, columns: int, rows: int
) -> None:
    from prompt_toolkit.data_structures import Size

    class Output(DummyOutput):
        def get_size(self) -> Size:
            return Size(rows=rows, columns=columns)

    async def run() -> None:
        with create_pipe_input() as pipe:
            monkeypatch.setattr(prompt_module, "PromptSession", partial(PromptSession, input=pipe, output=Output()))
            interrupted: list[bool] = []
            prompt = PromptToolkitInput(request_interrupt=lambda: interrupted.append(True))
            prompt.set_agent_running(True)
            prompt.set_status_lines(
                tuple(
                    PromptStatusLine(label, show_spinner=False)
                    for label in (
                        "Main working",
                        "Inspect source",
                        "Check output",
                        "Waiting for approval",
                        "+5 agents · /tasks",
                        "Steer main · /tasks · /stop agents",
                    )
                )
            )
            inputs = cast(AsyncGenerator[UserInputPayload], prompt._iter_inputs_inner())
            pending_input = asyncio.create_task(anext(inputs))
            await until(lambda: prompt._session.app.is_running)
            prompt._session.default_buffer.document = Document("current draft", 4)
            for _ in range(2):
                choice = asyncio.create_task(prompt.choose_task_action("Tasks", [_item("task", "task")]))
                await until(lambda: bool(prompt._task_picker and prompt._task_picker.is_open))
                assert prompt._get_picker_reserved_rows() + 4 < rows
                pipe.send_text("\x1b")
                assert await asyncio.wait_for(choice, 2) is None
                assert prompt._session.default_buffer.document == Document("current draft", 4)
                assert not interrupted and not pending_input.done()
            choice = asyncio.create_task(
                prompt.choose_task_action("Tasks", [_item("first", "first"), _item("second", "second")])
            )
            await until(lambda: bool(prompt._task_picker and prompt._task_picker.is_open))

            def rendered_lines() -> list[str]:
                screen = prompt._session.app.renderer._last_screen
                return (
                    []
                    if screen is None
                    else [
                        "".join(cell.char for _, cell in sorted(row.items()))
                        for _, row in sorted(screen.data_buffer.items())
                    ]
                )

            await until(lambda: any("second" in line for line in rendered_lines()))
            painted = rendered_lines()
            assert next(index for index, line in enumerate(painted) if "first" in line) != next(
                index for index, line in enumerate(painted) if "second" in line
            )
            assert any("current draft" in line for line in painted)
            assert not any("Window too small" in line for line in painted)
            pipe.send_text("\x1b[B\r")
            assert await asyncio.wait_for(choice, 2) == "second"
            choice = asyncio.create_task(
                prompt.choose_task_action("Message", [_item("Review", "review")], text_entry=True)
            )
            await until(lambda: bool(prompt._task_picker and prompt._task_picker.is_open))
            pipe.send_text("/stop is peer data\r")
            assert await asyncio.wait_for(choice, 2) == "/stop is peer data"
            assert prompt._session.default_buffer.document == Document("current draft", 4)
            assert not interrupted and not pending_input.done()

            class Client:
                async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
                    return TaskResponse(tasks=[task_snapshot("failed", description="Long task name " * 40)])

            panel = TaskPanel(cast(RuntimeClient, Client()), prompt, lambda: {})
            panel_task = asyncio.create_task(panel.open())
            await until(lambda: any("Agent · failed · Long task name" in line for line in rendered_lines()))
            pipe.send_text("\x1b")
            await asyncio.wait_for(panel_task, 2)
            assert prompt._session.default_buffer.document == Document("current draft", 4)
            prompt._session.default_buffer.document = Document("newer draft", 2)
            choice = asyncio.create_task(prompt.choose_task_action("Tasks", [_item("task", "task")]))
            await until(lambda: bool(prompt._task_picker and prompt._task_picker.is_open))
            resume = await prompt.pause_for_external_input()
            assert await choice is None
            assert not prompt._session.app.is_running
            assert prompt._resumed_buffer_text == "newer draft"
            assert prompt._resumed_cursor_position == 2
            resume()
            await until(lambda: prompt._session.app.is_running)
            assert prompt._session.default_buffer.document == Document("newer draft", 2)
            pending_input.cancel()
            await asyncio.gather(pending_input, return_exceptions=True)
            await inputs.aclose()
            prompt._bottom_bar.stop()

    asyncio.run(run())


@pytest.mark.parametrize("send_fails", [False, True])
def test_panel_pages_stops_owned_task_and_confirms_exact_peer_target_with_failure_feedback(send_fails: bool) -> None:
    class Client:
        def __init__(self) -> None:
            self.requests: list[TaskRequest] = []
            self.messages: list[tuple[str, str]] = []

        async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
            self.requests.append(request)
            if request.action == "stop":
                raise RuntimeError("owner rejected stop")
            return TaskResponse(
                tasks=[task_snapshot()],
                output="page one" if request.offset == 0 else "page two",
                truncated=request.action == "output" and request.offset == 0,
                next_offset=8,
            )

        async def send_task_message(self, task_id: str, body: str) -> PeerReceipt:
            self.messages.append((task_id, body))
            if send_fails:
                raise RuntimeError("peer queue rejected")
            return PeerReceipt(message_id="receipt", target="child")

    class Prompt:
        def __init__(self) -> None:
            self.choices = iter(
                [
                    "agent-1",
                    "output",
                    "next",
                    "previous",
                    "back",
                    "stop",
                    "message",
                    "/stop is peer data",
                    "send",
                    "back",
                    None,
                ]
            )
            self.headings: list[str] = []

        async def choose_task_action(self, heading: str, items: Any, **kwargs: Any) -> str | None:
            self.headings.append(heading)
            return next(self.choices)

    async def run() -> None:
        client, prompt = Client(), Prompt()
        await TaskPanel(cast(RuntimeClient, client), cast(PromptToolkitInput, prompt), lambda: {}).open()
        assert [(r.task_id, r.offset) for r in client.requests if r.action == "output"] == [
            ("agent-1", 0),
            ("agent-1", 8),
            ("agent-1", 0),
        ]
        assert client.messages == [("agent-1", "/stop is peer data")]
        assert any("stop failed: owner rejected stop" in heading for heading in prompt.headings)
        assert any(
            ("message failed: peer queue rejected" if send_fails else "Queued → child") in heading
            for heading in prompt.headings
        )
        assert any("Queued → child" in heading for heading in prompt.headings) is not send_fails

    asyncio.run(run())


def test_task_message_http_uses_selected_owned_child_and_external_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def request(method: str, path: str, **kwargs: Any) -> Any:
        calls.append((path, kwargs))
        if path.endswith("/tasks"):
            task = task_snapshot()
            task.ref.operation_id = "child-operation"
            return TaskResponse(tasks=[task]).model_dump()
        return {"message_id": "receipt", "target": "child", "accepted": True}

    monkeypatch.setattr(server_api, "_request", request)
    receipt = server_api.send_owned_task_message("main", "agent-1", "/stop")
    assert receipt.target == "child"
    path, params = calls[-1]
    assert path == "/api/headless/sessions/child/send-active"
    assert params["json_body"]["text"] == "/stop"
    assert "sender_session_id" not in params["json_body"]
    assert params["json_body"]["sender"].endswith("(external)")
    assert params["json_body"]["expected_operation_id"] == "child-operation"
    with pytest.raises(ValueError, match="owned child"):
        server_api.send_owned_task_message("foreign", "agent-1", "text")
    assert len([path for path, _ in calls if path.endswith("/send-active")]) == 1


def test_old_server_cannot_silently_fall_back_to_unguarded_send(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    def request(method: str, path: str, **kwargs: Any) -> Any:
        calls.append(path)
        if path.endswith("/tasks"):
            task = task_snapshot()
            task.ref.operation_id = "operation"
            return TaskResponse(tasks=[task]).model_dump()
        raise server_api.ServerAPIError(404, "Not Found")

    monkeypatch.setattr(server_api, "_request", request)
    with pytest.raises(RuntimeError, match=r"unsupported.*message not sent"):
        server_api.send_owned_task_message("main", "agent-1", "body")
    assert calls == ["/api/headless/sessions/main/tasks", "/api/headless/sessions/child/send-active"]


@pytest.mark.parametrize("status", ["completed", "failed", "stopping", "queued"])
def test_nonrunning_child_has_no_message_action_and_http_refuses_send(
    monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    task = task_snapshot(status)

    class Prompt:
        async def choose_task_action(self, heading: str, items: Any, **kwargs: Any) -> str | None:
            assert "output" in [item.value for item in items]
            assert "message" not in [item.value for item in items]
            assert ("stop" in [item.value for item in items]) == (status in {"stopping", "queued"})
            return None

    asyncio.run(TaskPanel(cast(RuntimeClient, None), cast(PromptToolkitInput, Prompt()), lambda: {})._detail(task))
    calls: list[str] = []

    def request(method: str, path: str, **kwargs: Any) -> Any:
        calls.append(path)
        return TaskResponse(tasks=[task]).model_dump()

    monkeypatch.setattr(server_api, "_request", request)
    with pytest.raises(ValueError, match="no longer running"):
        server_api.send_owned_task_message("main", "agent-1", "body")
    assert all(path.endswith("/tasks") for path in calls)


def test_picker_refresh_keeps_finished_tasks_and_prioritizes_attention_then_failure() -> None:
    tasks = []
    for task_id, status in (
        ("done", "completed"),
        ("running", "running"),
        ("failed", "failed"),
        ("waiting", "running"),
    ):
        task = task_snapshot(status, delivered=True)
        task.ref.task_id = task_id
        task.ref.session_id = task_id
        tasks.append(task)

    class Client:
        calls = 0

        async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
            assert request.action == "list"
            self.calls += 1
            return TaskResponse(tasks=tasks)

    class Prompt:
        calls = 0

        async def choose_task_action(self, heading: str, items: Any, **kwargs: Any) -> str | None:
            assert [item.value for item in items] == ["waiting", "failed", "running", "done", "refresh"]
            self.calls += 1
            return "refresh" if self.calls == 1 else None

    async def run() -> None:
        client = Client()
        await TaskPanel(
            cast(RuntimeClient, client), cast(PromptToolkitInput, Prompt()), lambda: {"waiting": "Needs input"}
        ).open()
        assert client.calls == 2

    asyncio.run(run())


def test_message_confirmation_cancel_never_sends() -> None:
    class Prompt:
        choices = iter(["/stop is peer data", "cancel"])

        async def choose_task_action(self, *args: Any, **kwargs: Any) -> str | None:
            return next(self.choices)

    panel = TaskPanel(cast(RuntimeClient, None), cast(PromptToolkitInput, Prompt()), lambda: {})
    assert asyncio.run(panel._message(task_snapshot())) == "Message not sent"
