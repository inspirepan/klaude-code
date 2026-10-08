from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, cast

import pytest
from starlette.websockets import WebSocketDisconnect

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import events, message, op
from klaude_code.protocol.shell_task import ShellTaskOutput, ShellTaskSnapshot
from klaude_code.server.routes import ws
from klaude_code.server.state import get_server_state_from_app
from klaude_code.tool.shell.task_manager import ShellTaskManager

from .conftest import AppEnv, usage


@pytest.fixture(autouse=True)
def _disable_side_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.should_suggest", lambda _session: "test")


def _call(app_env: AppEnv, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    assert app_env.client.portal is not None
    return app_env.client.portal.call(partial(function, *args, **kwargs))


def _wait(app_env: AppEnv, predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(0.01)

    _call(app_env, poll)


def _reply(app_env: AppEnv, *, delay_s: float = 0) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="done"),
        message.AssistantMessage(parts=[message.TextPart(text="done")], stop_reason="stop", usage=usage()),
        delay_s=delay_s,
    )


def _start(app_env: AppEnv, session_id: str, command: str = "sleep 60") -> ShellTaskSnapshot:
    return _call(
        app_env,
        app_env.runtime.shell_task_manager.start,
        session_id=session_id,
        command=command,
        description="test shell",
        work_dir=app_env.work_dir,
        env=dict(os.environ),
        timeout_ms=None,
        background=True,
    )


def _idle(app_env: AppEnv, session_id: str) -> bool:
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    return actor is not None and actor.snapshot().is_idle


def test_idle_completion_becomes_bounded_model_input(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _reply(app_env)
    task = _start(app_env, session_id, "printf 'shell output'")
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1 and _idle(app_env, session_id))
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    reports = [item.content for item in agent.session.get_history_item() if isinstance(item, events.UserMessageEvent)]
    assert len(reports) == 1
    assert task.task_id in reports[0]
    assert "status=completed, exit=0" in reports[0]
    assert "shell output" in reports[0]
    assert "untrusted_output" in reports[0]
    assert task.output_path in reports[0]


def test_busy_completion_waits_for_turn_and_does_not_interrupt(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _reply(app_env, delay_s=0.2)
    _reply(app_env)
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "user turn"})
    assert response.status_code == 200
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1)
    task = _start(app_env, session_id, "printf 'completion'")
    _call(app_env, app_env.runtime.shell_task_manager.wait_task, session_id, task.task_id)
    assert app_env.fake_llm.call_count == 1
    assert not _idle(app_env, session_id)
    _wait(app_env, lambda: app_env.fake_llm.call_count == 2 and _idle(app_env, session_id))
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    history = agent.session.conversation_history
    assert not any(isinstance(item, message.InterruptEntry) for item in history)
    assert len([item for item in history if isinstance(item, message.AssistantMessage)]) == 2, history


def test_interrupt_drops_pending_notification_even_after_real_input(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _reply(app_env, delay_s=10)
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "slow turn"})
    assert response.status_code == 200
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1)
    task = _start(app_env, session_id, "printf 'cancelled notification'")
    _call(app_env, app_env.runtime.shell_task_manager.wait_task, session_id, task.task_id)
    _call(app_env, app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
    _wait(app_env, lambda: _idle(app_env, session_id))
    _reply(app_env)
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "fresh user turn"})
    assert response.status_code == 200
    _wait(app_env, lambda: app_env.fake_llm.call_count == 2 and _idle(app_env, session_id))
    _call(app_env, asyncio.sleep, 0.1)
    assert app_env.fake_llm.call_count == 2
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    reports = [item.content for item in agent.session.get_history_item() if isinstance(item, events.UserMessageEvent)]
    assert not any(task.task_id in text for text in reports)


def test_running_shell_excludes_idle_reclaim(app_env: AppEnv) -> None:
    victim = app_env.create_session()
    shell_session = app_env.create_session()
    app_env.create_session()
    task = _start(app_env, shell_session)
    try:
        reclaimed = _call(app_env, app_env.runtime.reclaim_idle_sessions, idle_for_seconds=0)
        assert shell_session not in reclaimed
        assert victim in reclaimed
        assert app_env.runtime.shell_task_manager.active_session_ids() == {shell_session}
    finally:
        _call(app_env, app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=shell_session))
        _call(app_env, app_env.runtime.shell_task_manager.stop_task, shell_session, task.task_id)


def test_runtime_shutdown_stops_shell_and_suppresses_completion(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    task = _start(app_env, session_id)
    _call(app_env, app_env.runtime.stop)
    snapshots = _call(app_env, app_env.runtime.shell_task_manager.list_tasks, session_id)
    assert snapshots[0].task_id == task.task_id
    assert snapshots[0].status == "stopped"
    assert not app_env.runtime.shell_task_manager.has_running_tasks()
    assert app_env.fake_llm.call_count == 0


def test_stop_idle_session_does_not_revive_on_attach(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    gate = app_env.work_dir / "finish-shell"
    task = _start(app_env, session_id, f"while [ ! -e {gate.name} ]; do sleep 0.02; done; printf late")
    _call(app_env, app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?resume=1") as websocket:
        for _ in range(20):
            frame = websocket.receive_json()
            if isinstance(frame, dict) and frame.get("type") == "replay_complete":
                break
        else:
            raise AssertionError("Resume handshake did not finish")
        gate.touch()
        _call(app_env, app_env.runtime.shell_task_manager.wait_task, session_id, task.task_id)
        _call(app_env, asyncio.sleep, 0.1)
        assert app_env.fake_llm.call_count == 0


def test_shell_event_round_trip_retains_snapshot(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    task = _start(app_env, session_id)
    try:
        event = events.ShellTasksUpdatedEvent(session_id=session_id, tasks=[task])
        assert events.event_type_name(event) == "shell_tasks_updated"
        parsed = events.parse_event("shell_tasks_updated", event.model_dump(mode="json"))
        assert isinstance(parsed, events.ShellTasksUpdatedEvent)
        assert parsed.tasks == [task]
    finally:
        _call(app_env, app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
        _call(app_env, app_env.runtime.shell_task_manager.stop_task, session_id, task.task_id)


def test_completions_during_one_turn_are_batched_into_one_follow_up(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    _reply(app_env, delay_s=0.2)
    _reply(app_env)
    assert (
        app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "user turn"}).status_code == 200
    )
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1)
    first = _start(app_env, session_id, "printf first")
    second = _start(app_env, session_id, "printf second")
    for task in (first, second):
        _call(app_env, app_env.runtime.shell_task_manager.wait_task, session_id, task.task_id)
    _wait(app_env, lambda: app_env.fake_llm.call_count == 2 and _idle(app_env, session_id))
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    inputs = [item for item in agent.session.conversation_history if isinstance(item, message.UserMessage)]
    assert len(inputs) == 2
    report = inputs[-1].model_dump_json()
    assert first.task_id in report and second.task_id in report


def test_resume_loads_lost_snapshot_after_manager_restart(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    task = _start(app_env, session_id)
    _call(app_env, app_env.runtime.shell_task_manager.aclose)
    stale = task.model_copy(update={"status": "running", "exit_code": None, "ended_at": None})
    Path(task.output_path).with_suffix(".json").write_text(stale.model_dump_json(), encoding="utf-8")
    app_env.runtime.shell_task_manager = ShellTaskManager()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?resume=1") as websocket:
        received = []
        for _ in range(20):
            frame = websocket.receive_json()
            if isinstance(frame, dict) and frame.get("event_type") == "shell_tasks_updated":
                received = frame["event"]["tasks"]
            if isinstance(frame, dict) and frame.get("type") == "replay_complete":
                break
        else:
            raise AssertionError("Resume handshake did not finish")
        assert len(received) == 1
        assert received[0]["task_id"] == task.task_id
        assert received[0]["status"] == "lost"
        assert not app_env.runtime.shell_task_manager.has_running_tasks()
        assert app_env.fake_llm.call_count == 0


def test_detach_does_not_delete_empty_session_with_running_shell(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    task = _start(app_env, session_id)
    try:
        with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?resume=1") as websocket:
            for _ in range(20):
                frame = websocket.receive_json()
                if isinstance(frame, dict) and frame.get("type") == "replay_complete":
                    break
            else:
                raise AssertionError("Resume handshake did not finish")
        _call(app_env, asyncio.sleep, 0.05)
        assert app_env.runtime.session_registry.get_session_actor(session_id) is not None
        assert app_env.runtime.shell_task_manager.active_session_ids() == {session_id}
        assert app_env.fake_llm.call_count == 0
    finally:
        _call(app_env, app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
        _call(app_env, app_env.runtime.shell_task_manager.stop_task, session_id, task.task_id)


def test_user_turn_during_output_read_defers_notification_instead_of_losing_it(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = app_env.create_session()
    _reply(app_env, delay_s=0.2)
    _reply(app_env)
    manager = app_env.runtime.shell_task_manager
    original_read = manager.read_output
    reading = asyncio.Event()
    release = asyncio.Event()

    async def delayed_read(session_id: str, task_id: str, *, offset: int = 0, limit: int = 16384) -> ShellTaskOutput:
        if not reading.is_set():
            reading.set()
            await release.wait()
        return await original_read(session_id, task_id, offset=offset, limit=limit)

    monkeypatch.setattr(manager, "read_output", delayed_read)
    task = _start(app_env, session_id, "printf completion")
    _wait(app_env, reading.is_set)
    assert (
        app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "racing user"}).status_code
        == 200
    )
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1)
    _call(app_env, release.set)
    _wait(app_env, lambda: app_env.fake_llm.call_count == 2 and _idle(app_env, session_id))
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    inputs = [
        item.model_dump_json() for item in agent.session.conversation_history if isinstance(item, message.UserMessage)
    ]
    assert len(inputs) == 2
    assert "racing user" in inputs[0]
    assert task.task_id in inputs[1]


def test_snapshot_send_race_drops_older_queued_shell_state(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = app_env.create_session()
    state = get_server_state_from_app(cast(Any, app_env.client.app))
    monkeypatch.setattr(ws, "get_server_state_from_ws", lambda _websocket: state)
    seen: list[str] = []

    async def run() -> None:
        app_env.runtime.disable_shell_notifications(session_id)
        subscription = app_env.event_bus.subscribe(None)
        manager = app_env.runtime.shell_task_manager
        task = await manager.start(
            session_id=session_id,
            work_dir=app_env.work_dir,
            command="sleep 60",
            description="snapshot race",
            timeout_ms=None,
            env=dict(os.environ),
            background=True,
        )

        class Socket:
            async def send_json(self, payload: Any) -> None:
                items = payload if isinstance(payload, list) else [payload]
                for item in items:
                    if item.get("event_type") != "shell_tasks_updated":
                        continue
                    status = item["event"]["tasks"][0]["status"]
                    seen.append(status)
                    if len(seen) == 1:
                        # Update state while the captured snapshot is being sent.
                        await manager.stop_task(session_id, task.task_id)
                    elif status == "stopped":
                        raise WebSocketDisconnect()

        socket = cast(Any, Socket())
        cutoffs = await ws._send_shell_task_snapshots(session_id, app_env.work_dir, socket, state=state)
        await asyncio.wait_for(
            ws._forward_events(session_id, socket, subscription=subscription, shell_snapshot_cutoffs=cutoffs),
            timeout=1,
        )

    _call(app_env, run)
    assert seen[0] == "running"
    assert seen[-1] == "stopped"
    assert "running" not in seen[1:]
    assert app_env.fake_llm.call_count == 0


def test_parent_stop_latches_child_notifications_before_cancellation_wait(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent_id = app_env.create_session()
    child_id = app_env.create_session()
    child_actor = app_env.runtime.session_registry.get_session_actor(child_id)
    assert child_actor is not None
    child = child_actor.get_agent()
    assert child is not None
    child.session.parent_session_id = parent_id
    handler = app_env.runtime._operation_dispatcher._agent_operation_handler
    original_interrupt = handler.interrupt
    cancelling = asyncio.Event()
    release = asyncio.Event()

    async def delayed_interrupt(session_id: str, **kwargs: Any) -> bool:
        if session_id == parent_id:
            cancelling.set()
            await release.wait()
        return await original_interrupt(session_id, **kwargs)

    monkeypatch.setattr(handler, "interrupt", delayed_interrupt)
    operation = op.InterruptOperation(session_id=parent_id)
    _call(app_env, app_env.runtime.submit, operation)
    try:
        _wait(app_env, cancelling.is_set)
        task = _start(app_env, child_id, "printf child-completion")
        _call(app_env, app_env.runtime.shell_task_manager.wait_task, child_id, task.task_id)
        _call(app_env, asyncio.sleep, 0.05)
        assert app_env.runtime.shell_notification_generation(child_id) is None
        assert app_env.fake_llm.call_count == 0
    finally:
        _call(app_env, release.set)
        _call(app_env, app_env.runtime.wait_for, operation.id)
