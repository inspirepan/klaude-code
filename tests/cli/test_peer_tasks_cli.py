from __future__ import annotations

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from klaude_code.cli import headless_cmd
from klaude_code.cli.main import app
from klaude_code.protocol.background_task import BackgroundTaskSnapshot, TaskReference, TaskResponse


def test_send_receipt_and_run_session_are_peer_data_not_environment_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []
    receipt = {"session_id": "target", "mode": "queued", "message_id": "msg", "target": "target", "accepted": True}

    def api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        assert method == "POST" and path.endswith("/target/send")
        calls.append(kwargs["json_body"])
        return receipt

    monkeypatch.setattr(headless_cmd, "_api", api)
    monkeypatch.setenv("KLAUDE_SESSION_ID", "forged")
    for args in (
        [
            "send",
            "target",
            "hello",
            "--from",
            "display",
            "--steer",
            "--message-id",
            "msg",
            "--reply-to",
            "previous",
            "--json",
        ],
        ["run", "--session", "target", "hello", "--json"],
    ):
        result = CliRunner().invoke(app, args)
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == receipt
    assert all("sender_session_id" not in body for body in calls)
    assert calls[0]["sender"] == "display" and calls[0]["steer"] is True
    assert calls[0]["message_id"] == "msg" and calls[0]["reply_to"] == "previous"


@pytest.mark.parametrize("action", ["list", "output", "wait", "stop"])
def test_tasks_cli_uses_typed_owner_request_and_long_poll_timeout(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    calls: list[dict[str, Any]] = []
    task = BackgroundTaskSnapshot(
        ref=TaskReference(kind="agent", owner_session_id="owner", task_id="task", run_id="run"),
        status="completed",
        started_at=1,
        delivery_id="delivery",
    )

    def api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        assert method == "POST" and path == "/api/headless/sessions/owner/tasks"
        calls.append(kwargs)
        return TaskResponse(tasks=[task], output="report").model_dump()

    monkeypatch.setattr(headless_cmd, "_api", api)
    args = ["tasks", action, "owner", *([] if action == "list" else ["task"]), "--json"]
    result = CliRunner().invoke(app, args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["output"] == "report"
    assert calls[0]["json_body"]["action"] == action
    assert calls[0]["json_body"]["task_id"] == (None if action == "list" else "task")
    if action == "wait":
        assert calls[0]["timeout"] > calls[0]["json_body"]["wait_ms"] / 1000


def test_tasks_wait_timeout_uses_exit_124_without_stopping_task(monkeypatch: pytest.MonkeyPatch) -> None:
    actions: list[str] = []

    def api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        actions.append(kwargs["json_body"]["action"])
        return TaskResponse(
            tasks=[
                BackgroundTaskSnapshot(
                    ref=TaskReference(kind="shell", owner_session_id="owner", task_id="task", run_id="task"),
                    status="running",
                    started_at=1,
                    delivery_id="delivery",
                )
            ]
        ).model_dump()

    monkeypatch.setattr(headless_cmd, "_api", api)
    result = CliRunner().invoke(app, ["tasks", "wait", "owner", "task", "--timeout", "0", "--json"])
    assert result.exit_code == 124
    assert actions == ["wait"]
    assert json.loads(result.output)["tasks"][0]["status"] == "running"


def test_stop_and_kill_have_separate_control_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    paths: list[str] = []

    def api(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        paths.append(path)
        return {"session_id": "owner", "was": "running", "scope": "sub_agents", "status": "completed"}

    monkeypatch.setattr(headless_cmd, "_api", api)
    assert CliRunner().invoke(app, ["stop", "owner", "--children", "--json"]).exit_code == 0
    assert CliRunner().invoke(app, ["kill", "owner"]).exit_code == 0
    assert paths == ["/api/headless/sessions/owner/stop", "/api/headless/sessions/owner/interrupt"]
