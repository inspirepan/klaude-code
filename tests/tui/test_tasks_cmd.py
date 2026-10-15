import asyncio
from types import SimpleNamespace
from typing import cast

import pytest

from klaude_code.protocol import events, message, op
from klaude_code.tui.command import dispatch_command, get_command_info_list, has_background_command
from klaude_code.tui.command.command_abc import Agent


@pytest.mark.parametrize(
    ("text", "action", "task_id", "offset", "limit"),
    [
        ("/tasks list", "list", None, 0, 16384),
        ("/tasks output shell-1", "output", "shell-1", 0, 16384),
        ("/tasks output shell-1 20 512", "output", "shell-1", 20, 512),
        ("/tasks output shell-1 20 32768", "output", "shell-1", 20, 32768),
        ("/tasks stop shell-1", "stop", "shell-1", 0, 16384),
        ("/tasks output agent-1 20 512", "output", "agent-1", 20, 512),
        ("/tasks stop agent-1", "stop", "agent-1", 0, 16384),
        ("/tasks wait agent-1 20 512 10", "wait", "agent-1", 20, 512),
    ],
)
def test_tasks_dispatches_management_without_an_agent_turn(
    text: str, action: str, task_id: str | None, offset: int, limit: int
) -> None:
    agent = cast(Agent, SimpleNamespace(session=SimpleNamespace(id="main")))
    result = asyncio.run(dispatch_command(message.UserInputPayload(text=text), agent, submission_id="request"))
    assert has_background_command(text)
    assert result.events is None
    assert result.operations is not None and len(result.operations) == 1
    operation = result.operations[0]
    assert isinstance(operation, op.ManageTasksOperation)
    request = operation.request
    assert (operation.session_id, request.action, request.task_id, request.offset, request.limit) == (
        "main",
        action,
        task_id,
        offset,
        limit,
    )


@pytest.mark.parametrize("args", ["stop", "output", "output t bad", "output t 0 bad", "output t 0 1 extra", "unknown"])
def test_tasks_invalid_arguments_show_usage_without_submitting(args: str) -> None:
    agent = cast(Agent, SimpleNamespace(session=SimpleNamespace(id="main")))
    result = asyncio.run(
        dispatch_command(message.UserInputPayload(text=f"/tasks {args}"), agent, submission_id="request")
    )
    assert not result.operations
    assert result.events is not None
    notice = result.events[0]
    assert isinstance(notice, events.NoticeEvent) and notice.is_error
    assert "output TASK_ID" in notice.content and "stop TASK_ID" in notice.content


@pytest.mark.parametrize(
    ("args", "field", "bound"),
    [
        ("output t -1", "offset", "0"),
        ("output t 0 0", "limit", "0"),
        ("output t 0 1048577", "limit", "1048576"),
        ("wait t 0 1 300001", "wait_ms", "300000"),
    ],
)
def test_tasks_uses_operation_validation_for_numeric_constraints(args: str, field: str, bound: str) -> None:
    agent = cast(Agent, SimpleNamespace(session=SimpleNamespace(id="main")))
    result = asyncio.run(
        dispatch_command(message.UserInputPayload(text=f"/tasks {args}"), agent, submission_id="request")
    )
    assert not result.operations
    assert result.events is not None
    notice = result.events[0]
    assert isinstance(notice, events.NoticeEvent) and notice.is_error
    assert f"{field}:" in notice.content and bound in notice.content


def test_tasks_completion_exposes_supported_actions() -> None:
    info = next(command for command in get_command_info_list() if command.name == "tasks")
    assert info.support_addition_params
    assert "list" in info.placeholder and "output TASK_ID" in info.placeholder and "stop TASK_ID" in info.placeholder


def test_tasks_without_arguments_opens_client_panel_without_runtime_operation() -> None:
    agent = cast(Agent, SimpleNamespace(session=SimpleNamespace(id="main")))
    result = asyncio.run(dispatch_command(message.UserInputPayload(text="/tasks"), agent, submission_id="request"))
    assert result.open_task_panel
    assert not result.events and not result.operations
