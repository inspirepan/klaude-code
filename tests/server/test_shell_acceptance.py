from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI

from klaude_code.agent.runtime import agent_ops
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import events, llm_param, message, op, tools
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.server.state import get_server_state_from_app

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, op_frame, receive_events, usage

pytestmark = pytest.mark.timeout(20)


@pytest.fixture(autouse=True)
def isolate_auxiliary_model_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    async def no_title(**_kwargs: Any) -> None:
        return None

    # Keep the scripted client exclusively for agent turns, not title/suggestion forks.
    monkeypatch.setattr(agent_ops, "generate_session_title", no_title)
    monkeypatch.setattr(agent_ops, "should_suggest", lambda _session: "shell acceptance test")


@pytest.fixture
def model_inputs(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> list[llm_param.LLMCallParameter]:
    captured: list[llm_param.LLMCallParameter] = []
    original_call = app_env.fake_llm.call

    async def capture(param: llm_param.LLMCallParameter) -> LLMStreamABC:
        captured.append(param.model_copy(deep=True))
        return await original_call(param)

    monkeypatch.setattr(app_env.fake_llm, "call", capture)
    monkeypatch.setattr(app_env.fake_llm, "acceptance_inputs", captured, raising=False)
    return captured


def _wait(app_env: AppEnv, predicate: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    actors = app_env.runtime.session_registry.list_session_actors()
    states = {actor.session_id: repr(actor.snapshot()) for actor in actors}
    captured: list[llm_param.LLMCallParameter] = getattr(app_env.fake_llm, "acceptance_inputs", [])
    inputs = [
        {
            "session_id": param.session_id,
            "has_tools": bool(param.tools),
            "input_tail": [item.model_dump(mode="json") for item in param.input[-3:]],
        }
        for param in captured
    ]
    assert isinstance(app_env.client.app, FastAPI)
    server_state = get_server_state_from_app(app_env.client.app)
    errors = []
    if server_state.tapes is not None:
        for actor in actors:
            cut = server_state.tapes.cut(actor.session_id)
            if cut is not None:
                errors.extend(
                    envelope.event.model_dump(mode="json")
                    for envelope in cut.envelopes
                    if isinstance(envelope.event, events.ErrorEvent)
                )
    pytest.fail(
        f"Acceptance wait expired: LLM calls={app_env.fake_llm.call_count}; actors={states}; "
        f"model_inputs={json.dumps(inputs)[:12000]}; errors={json.dumps(errors)[:4000]}"
    )


def _idle(app_env: AppEnv, session_id: str) -> bool:
    snapshot = app_env.runtime.session_registry.snapshot(session_id)
    return snapshot is not None and snapshot.is_idle


def _tasks(app_env: AppEnv, session_id: str) -> list[ShellTaskSnapshot]:
    assert app_env.client.portal is not None
    return app_env.client.portal.call(app_env.runtime.shell_task_manager.list_tasks, session_id)


def _cleanup(app_env: AppEnv, session_id: str) -> None:
    assert app_env.client.portal is not None
    app_env.client.portal.call(app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
    app_env.client.portal.call(app_env.runtime.shell_task_manager.stop_session, session_id)


def _gate_command(gate: Path) -> str:
    # Repeat the PID after the gate to detect a restarted command or duplicate execution.
    return f"printf 'START:%s\\n' \"$$\"; while [ ! -e {gate.name} ]; do sleep 0.02; done; printf 'DONE:%s\\n' \"$$\""


def _enqueue_bash(app_env: AppEnv, *commands: str) -> None:
    parts: list[message.Part] = [
        message.ToolCallPart(
            call_id=f"bash-{index}",
            tool_name=tools.BASH,
            arguments_json=json.dumps(
                {"command": command, "description": "Acceptance shell", "wait_ms": 1, "timeout_ms": 15000}
            ),
        )
        for index, command in enumerate(commands)
    ]
    app_env.fake_llm.enqueue(message.AssistantMessage(parts=parts, stop_reason="tool_use", usage=usage()))


def _enqueue_reply(app_env: AppEnv, *, delay_s: float = 0) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantMessage(parts=[message.TextPart(text="Accepted")], stop_reason="stop", usage=usage()),
        delay_s=delay_s,
    )


def _start_background(app_env: AppEnv, session_id: str, gate: Path) -> ShellTaskSnapshot:
    _enqueue_bash(app_env, _gate_command(gate))
    _enqueue_reply(app_env)
    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "Run the shell"})
    assert response.status_code == 200
    _wait(app_env, lambda: app_env.fake_llm.call_count == 2 and _idle(app_env, session_id))
    tasks = _tasks(app_env, session_id)
    assert len(tasks) == 1
    assert tasks[0].status == "running"
    assert tasks[0].background
    return tasks[0]


def _operation_finished(websocket: Any, operation: op.Operation) -> list[dict[str, Any]]:
    observed: list[dict[str, Any]] = []
    for _ in range(100):
        for event in receive_events(websocket):
            observed.append(event)
            if event.get("event_type") == "operation.finished" and event["event"]["operation_id"] == operation.id:
                assert event["event"]["status"] == "completed", observed
                return observed
    raise AssertionError(f"Operation did not finish: {operation.id}")


def test_real_bash_handoff_continues_same_process_and_wakes_model(
    app_env: AppEnv, model_inputs: list[llm_param.LLMCallParameter]
) -> None:
    session_id = app_env.create_session()
    gate = app_env.work_dir / "release"
    try:
        task = _start_background(app_env, session_id, gate)
        tool_results = [item for item in model_inputs[1].input if isinstance(item, message.ToolResultMessage)]
        assert len(tool_results) == 1
        assert task.task_id in tool_results[0].output_text
        assert tool_results[0].status == "success"

        _enqueue_reply(app_env)
        gate.touch()
        _wait(app_env, lambda: app_env.fake_llm.call_count == 3 and _idle(app_env, session_id))
        assert len(model_inputs) == 3
        completion_inputs = [item for item in model_inputs[2].input if isinstance(item, message.UserMessage)]
        report = completion_inputs[-1].model_dump_json()
        assert task.task_id in report
        assert "status=completed" in report
        assert f"DONE:{task.pid}" in report

        assert app_env.client.portal is not None
        page = app_env.client.portal.call(app_env.runtime.shell_task_manager.read_output, session_id, task.task_id)
        assert page.task.status == "completed"
        assert page.task.exit_code == 0
        assert page.task.pid == task.pid
        assert page.output.splitlines() == [f"START:{task.pid}", f"DONE:{task.pid}"]
    finally:
        _cleanup(app_env, session_id)


def test_busy_stop_and_interrupt_do_not_allow_late_completion_to_wake_model(
    app_env: AppEnv, model_inputs: list[llm_param.LLMCallParameter]
) -> None:
    session_id = app_env.create_session()
    first_gate = app_env.work_dir / "release-first"
    second_gate = app_env.work_dir / "release-second"
    try:
        _enqueue_bash(app_env, _gate_command(first_gate), _gate_command(second_gate))
        _enqueue_reply(app_env, delay_s=10)
        with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
            consume_ws_handshake(websocket)
            run = op.RunAgentOperation(session_id=session_id, input=message.UserInputPayload(text="Run two shells"))
            websocket.send_json(op_frame(run))
            _wait(app_env, lambda: app_env.fake_llm.call_count == 2)
            tasks = _tasks(app_env, session_id)
            assert len(tasks) == 2
            assert all(task.status == "running" for task in tasks)
            assert not _idle(app_env, session_id)

            stop = op.ManageShellOperation(session_id=session_id, action="stop", task_id=tasks[0].task_id)
            websocket.send_json(op_frame(stop))
            _operation_finished(websocket, stop)
            assert _tasks(app_env, session_id)[0].status == "stopped"
            assert not _idle(app_env, session_id), "ManageShell must not wait for the slow model turn"

            interrupt = op.InterruptOperation(session_id=session_id)
            websocket.send_json(op_frame(interrupt))
            _operation_finished(websocket, interrupt)
            _wait(app_env, lambda: _idle(app_env, session_id))
            assert _tasks(app_env, session_id)[1].status == "running"

            second_gate.touch()
            _wait(app_env, lambda: Path(tasks[1].output_path).read_text().count("DONE:") == 1)
            _wait(app_env, lambda: _tasks(app_env, session_id)[1].status == "completed")
            inspect = op.ManageShellOperation(session_id=session_id, action="output", task_id=tasks[1].task_id)
            websocket.send_json(op_frame(inspect))
            _operation_finished(websocket, inspect)
            assert app_env.client.portal is not None
            app_env.client.portal.call(asyncio.sleep, 0.2)
            assert len(model_inputs) == 2
            assert app_env.fake_llm.call_count == 2
            assert _idle(app_env, session_id)
    finally:
        _cleanup(app_env, session_id)


@pytest.mark.parametrize("mode", ["replay", "resume"])
def test_attach_restores_real_background_task_without_cross_session_leak(app_env: AppEnv, mode: str) -> None:
    session_id = app_env.create_session()
    other_session_id = app_env.create_session()
    gate = app_env.work_dir / "release"
    try:
        task = _start_background(app_env, session_id, gate)
        for attached_id in (session_id, other_session_id):
            with app_env.client.websocket_connect(f"/api/sessions/{attached_id}/ws?{mode}=1") as websocket:
                assert websocket.receive_json()["type"] == "connection_info"
                info = websocket.receive_json()
                assert info["type"] == "session_info"
                assert info["session_id"] == attached_id
                snapshots = []
                for _ in range(100):
                    frame = websocket.receive_json()
                    items = frame if isinstance(frame, list) else [frame]
                    snapshots.extend(item for item in items if item.get("event_type") == "shell_tasks_updated")
                    if any(item.get("type") == "replay_complete" for item in items):
                        break
                else:
                    pytest.fail("Attach handshake did not finish")
                assert len(snapshots) == 1
                assert snapshots[0]["session_id"] == attached_id
                restored = [ShellTaskSnapshot.model_validate(item) for item in snapshots[0]["event"]["tasks"]]
                assert restored == ([task] if attached_id == session_id else [])
        assert _tasks(app_env, other_session_id) == []
    finally:
        _cleanup(app_env, session_id)


def test_idle_reload_waits_for_background_shell_even_without_active_model(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    gate = app_env.work_dir / "release"
    try:
        task = _start_background(app_env, session_id, gate)
        assert _idle(app_env, session_id)
        refusal = app_env.client.post("/api/server/reload", json={"force": False})
        assert refusal.status_code == 409
        assert refusal.json()["detail"]["sessions"] == [{"session_id": session_id, "state": "running"}]

        # Stop notifications through the same user-facing interrupt path, then allow idle reload.
        assert app_env.client.portal is not None
        app_env.client.portal.call(app_env.runtime.submit_and_wait, op.InterruptOperation(session_id=session_id))
        pending = app_env.client.post("/api/server/reload", json={"force": False, "when": "idle"})
        assert pending.status_code == 200
        assert pending.json()["state"] == "pending"
        assert not app_env.lifecycle.reload_requested
        assert app_env.exit_calls == []

        gate.touch()
        _wait(app_env, lambda: app_env.lifecycle.reload_requested)
        assert _tasks(app_env, session_id)[0].task_id == task.task_id
        assert _tasks(app_env, session_id)[0].status == "completed"
        assert app_env.exit_calls == [True]
        assert app_env.fake_llm.call_count == 2
    finally:
        _cleanup(app_env, session_id)


def test_user_bash_is_synchronous_and_never_wakes_model(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    gate = app_env.work_dir / "release"
    try:
        with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
            consume_ws_handshake(websocket)
            run = op.RunBashOperation(session_id=session_id, command=_gate_command(gate))
            websocket.send_json(op_frame(run))
            started = collect_events_until(websocket, "bash.command.output.delta")
            assert "START:" in json.dumps(started)
            assert not _idle(app_env, session_id)
            assert _tasks(app_env, session_id) == []
            assert app_env.fake_llm.call_count == 0
            gate.touch()
            observed = _operation_finished(websocket, run)
            assert "DONE:" in json.dumps(observed)
            _wait(app_env, lambda: _idle(app_env, session_id))
            assert _tasks(app_env, session_id) == []
            assert app_env.fake_llm.call_count == 0
    finally:
        _cleanup(app_env, session_id)
