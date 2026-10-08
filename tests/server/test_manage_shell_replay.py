from __future__ import annotations

import os
from functools import partial
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import events, message, tools
from klaude_code.server.routes import ws
from klaude_code.server.state import get_server_state_from_app
from klaude_code.session.session import Session
from klaude_code.tool.shell.task_manager import ShellTaskManager

from .conftest import AppEnv


@pytest.fixture(autouse=True)
def _disable_side_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.should_suggest", lambda _session: "test")


class CaptureSocket:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_json(self, payload: Any) -> None:
        self.frames.extend(payload if isinstance(payload, list) else [payload])


@pytest.mark.parametrize("source", ["history", "tape"])
@pytest.mark.parametrize("lookup", ["known", "unknown", "foreign"])
def test_attach_manage_shell_hint_preserves_source_and_is_session_scoped(
    app_env: AppEnv,
    monkeypatch: pytest.MonkeyPatch,
    source: Literal["history", "tape"],
    lookup: Literal["known", "unknown", "foreign"],
) -> None:
    session_id = app_env.create_session()
    owner_id = app_env.create_session() if lookup == "foreign" else session_id
    state = get_server_state_from_app(cast(Any, app_env.client.app))

    async def run() -> None:
        app_env.runtime.disable_shell_notifications(owner_id)
        manager = app_env.runtime.shell_task_manager
        task = await manager.start(
            session_id=owner_id,
            work_dir=app_env.work_dir,
            command="sleep 60",
            description="wait for replay regression",
            timeout_ms=None,
            env=dict(os.environ),
            background=True,
        )
        try:
            task_id = "0" * 32 if lookup == "unknown" else task.task_id
            arguments = '{ "action": "wait", "task_id": "' + task_id + '", "wait_ms": 10000 }'
            call = events.ToolCallEvent(
                session_id=session_id,
                tool_call_id="pending-wait",
                tool_name=tools.MANAGE_SHELL,
                arguments=arguments,
                response_id="response",
            )
            actor = app_env.runtime.session_registry.get_session_actor(session_id)
            assert actor is not None
            agent = actor.get_agent()
            assert agent is not None
            if source == "history":
                agent.session.append_history(
                    [
                        message.AssistantMessage(
                            response_id=call.response_id,
                            parts=[
                                message.ToolCallPart(
                                    call_id=call.tool_call_id,
                                    tool_name=call.tool_name,
                                    arguments_json=arguments,
                                )
                            ],
                            stop_reason="tool_use",
                        )
                    ]
                )
            history_before = [item.model_dump_json() for item in agent.session.conversation_history]
            original_history_calls: list[events.ToolCallEvent] = []
            get_history_item = Session.get_history_item

            def capture_history(session: Session, limit: int | None = None) -> list[events.ReplayEventUnion]:
                items = list(get_history_item(session, limit=limit))
                original_history_calls.extend(item for item in items if isinstance(item, events.ToolCallEvent))
                return items

            monkeypatch.setattr(Session, "get_history_item", capture_history)
            assert state.tapes is not None
            state.tapes.drop(session_id)
            # This stale shell update must not precede the pending call on replay.
            await app_env.event_bus.publish(events.ShellTasksUpdatedEvent(session_id=session_id, tasks=[]))
            if source == "tape":
                await app_env.event_bus.publish(
                    call, operation_id="operation", task_id="root-task", causation_id="cause"
                )
            cut = state.tapes.cut(session_id)
            assert cut is not None
            tape_before = [item.model_dump_json(serialize_as_any=True) for item in cut.envelopes]
            socket = CaptureSocket()
            max_seq = await ws._send_attach_replay(session_id, cast(Any, socket), state=state)
            assert max_seq == cut.max_event_seq
            assert not any(frame.get("event_type") == "shell_tasks_updated" for frame in socket.frames)
            replay_calls = [
                item
                for frame in socket.frames
                for item in (frame["events"] if frame.get("type") == "replay_history" else [frame])
                if item.get("event_type") == "tool.call"
            ]
            assert len(replay_calls) == 1
            replay = replay_calls[0]
            parsed = events.parse_event("tool.call", replay["event"])
            assert isinstance(parsed, events.ToolCallEvent)
            assert parsed.arguments == arguments
            assert parsed.session_id == session_id
            assert parsed.response_id == call.response_id
            if lookup == "known":
                assert parsed.shell_task is not None
                assert parsed.shell_task.task_id == task.task_id
                assert parsed.shell_task.session_id == session_id
                assert parsed.shell_task.description == task.description
                assert parsed.shell_task.status == "running"
            else:
                assert parsed.shell_task is None
                assert "shell_task" not in replay["event"]
            if source == "tape":
                expected = cut.envelopes[-1].model_dump(mode="json", exclude_none=True, serialize_as_any=True)
                assert {key: value for key, value in replay.items() if key != "event"} == {
                    key: value for key, value in expected.items() if key != "event"
                }
            assert call.shell_task is None
            assert len(original_history_calls) == (1 if source == "history" else 0)
            assert all(item.shell_task is None for item in original_history_calls)
            assert history_before == [item.model_dump_json() for item in agent.session.conversation_history]
            assert tape_before == [item.model_dump_json(serialize_as_any=True) for item in cut.envelopes]
            assert all(
                item.shell_task is None
                for item in agent.session.get_history_item()
                if isinstance(item, events.ToolCallEvent)
            )
            assert not any(frame.get("event_type") == "tool.result" for frame in socket.frames)
            snapshot_start = len(socket.frames)
            await ws._send_shell_task_snapshots(session_id, app_env.work_dir, cast(Any, socket), state=state)
            assert all(frame["event_type"] == "shell_tasks_updated" for frame in socket.frames[snapshot_start:])
            assert app_env.fake_llm.call_count == 0
        finally:
            await manager.stop_task(owner_id, task.task_id)

    assert app_env.client.portal is not None
    app_env.client.portal.call(run)


@pytest.mark.parametrize("arguments", ["not json", "[]", "{}", '{"task_id": 123}'])
def test_attach_manage_shell_invalid_arguments_have_no_hint(app_env: AppEnv, arguments: str) -> None:
    session_id = app_env.create_session()
    state = get_server_state_from_app(cast(Any, app_env.client.app))

    async def run() -> None:
        call = events.ToolCallEvent(
            session_id=session_id, tool_call_id="invalid", tool_name=tools.MANAGE_SHELL, arguments=arguments
        )
        await app_env.event_bus.publish(call)
        socket = CaptureSocket()
        await ws._send_attach_replay(session_id, cast(Any, socket), state=state)
        replay = next(frame for frame in socket.frames if frame.get("event_type") == "tool.call")
        assert replay["event"]["arguments"] == arguments
        assert "shell_task" not in replay["event"]

    assert app_env.client.portal is not None
    app_env.client.portal.call(run)


def test_attach_manage_shell_recovers_snapshot_from_session_work_dir(app_env: AppEnv, tmp_path: Path) -> None:
    work_dir = tmp_path / "other-project"
    work_dir.mkdir()
    session_id = app_env.create_session(work_dir)
    state = get_server_state_from_app(cast(Any, app_env.client.app))

    async def run() -> None:
        app_env.runtime.disable_shell_notifications(session_id)
        manager = app_env.runtime.shell_task_manager
        task = await manager.start(
            session_id=session_id,
            work_dir=work_dir,
            command="sleep 60",
            description="recover other project task",
            timeout_ms=None,
            env=dict(os.environ),
            background=True,
        )
        restored_manager = ShellTaskManager()
        try:
            await manager.stop_task(session_id, task.task_id)
            call = events.ToolCallEvent(
                session_id=session_id,
                tool_call_id="restored",
                tool_name=tools.MANAGE_SHELL,
                arguments='{"action":"wait","task_id":"' + task.task_id + '"}',
            )
            await app_env.event_bus.publish(call)
            app_env.runtime.shell_task_manager = restored_manager
            socket = CaptureSocket()
            await ws._send_attach_replay(session_id, cast(Any, socket), state=state)
            replay = next(frame for frame in socket.frames if frame.get("event_type") == "tool.call")
            assert replay["event"]["shell_task"]["description"] == task.description
            assert replay["event"]["shell_task"]["work_dir"] == str(work_dir)
            assert replay["event"]["shell_task"]["status"] == "stopped"
            assert call.shell_task is None
        finally:
            app_env.runtime.shell_task_manager = manager
            await restored_manager.aclose()
            await manager.stop_task(session_id, task.task_id)

    assert app_env.client.portal is not None
    app_env.client.portal.call(run)


def test_attach_manage_shell_without_manager_has_no_hint(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = app_env.create_session()
    state = get_server_state_from_app(cast(Any, app_env.client.app))
    call = events.ToolCallEvent(
        session_id=session_id,
        tool_call_id="no-manager",
        tool_name=tools.MANAGE_SHELL,
        arguments='{"action":"wait","task_id":"' + "0" * 32 + '"}',
    )
    assert app_env.client.portal is not None
    app_env.client.portal.call(partial(app_env.event_bus.publish, call))
    socket = CaptureSocket()
    with monkeypatch.context() as patch:
        patch.delattr(app_env.runtime, "shell_task_manager")
        app_env.client.portal.call(partial(ws._send_attach_replay, session_id, cast(Any, socket), state=state))
    replay = next(frame for frame in socket.frames if frame.get("event_type") == "tool.call")
    assert "shell_task" not in replay["event"]
