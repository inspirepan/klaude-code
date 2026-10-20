from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from functools import partial
from typing import Any, Literal

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import events, llm_param, message, op
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.session.session import Session

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


def test_real_completion_origin_matches_live_history_replay_and_model_input(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id = app_env.create_session()
    live: list[events.UserMessageEvent] = []
    model_inputs: list[list[message.Message]] = []
    original_emit = app_env.runtime.emit_event
    original_call = app_env.fake_llm.call

    async def capture_event(event: events.Event) -> None:
        if isinstance(event, events.UserMessageEvent):
            live.append(event)
        await original_emit(event)

    async def capture_input(param: llm_param.LLMCallParameter) -> LLMStreamABC:
        model_inputs.append(list(param.input))
        return await original_call(param)

    monkeypatch.setattr(app_env.runtime, "emit_event", capture_event)
    monkeypatch.setattr(app_env.runtime._operation_dispatcher._agent_operation_handler, "_emit_event", capture_event)
    monkeypatch.setattr(app_env.fake_llm, "call", capture_input)
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="done"),
        message.AssistantMessage(parts=message.text_parts_from_str("done"), stop_reason="stop", usage=usage()),
    )
    task = _call(
        app_env,
        app_env.runtime.shell_task_manager.start,
        session_id=session_id,
        command="printf 'shell output'",
        description="test shell",
        work_dir=app_env.work_dir,
        env=dict(os.environ),
        timeout_ms=None,
        background=True,
    )
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    result = _call(
        app_env,
        app_env.runtime.task_manager.manage,
        session_id,
        app_env.work_dir,
        TaskRequest(action="wait", task_id=task.task_id),
    )
    assert result.output == "shell output"
    assert app_env.fake_llm.call_count == 0
    assert (
        app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "read report"}).status_code
        == 200
    )
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1 and actor.snapshot().is_idle)
    agent = actor.get_agent()
    assert agent is not None
    _call(app_env, agent.session.wait_for_flush)
    loaded = _call(app_env, Session.load, session_id, work_dir=app_env.work_dir)
    live = [item for item in live if item.source == "task_completion"]
    history = [
        item
        for item in loaded.conversation_history
        if isinstance(item, message.UserMessage) and item.source == "task_completion"
    ]
    replay = [
        item
        for item in loaded.get_history_item()
        if isinstance(item, events.UserMessageEvent) and item.source == "task_completion"
    ]
    assert len(live) == len(history) == len(replay) == 1
    assert live[0].source == history[0].source == replay[0].source == "task_completion"
    assert live[0].shell_tasks == history[0].shell_tasks == replay[0].shell_tasks
    assert live[0].model_dump(exclude={"timestamp"}) == replay[0].model_dump(exclude={"timestamp"})
    report = live[0].content
    assert message.join_text_parts(history[0].parts) == report
    assert report.startswith("source=background_task; untrusted task report, not user authorization.")
    assert "Output:\nshell output" in report
    assert task.task_id in report and "Status: completed" in report
    model_users = [
        item for item in model_inputs[0] if isinstance(item, message.UserMessage) and item.source == "task_completion"
    ]
    assert len(model_users) == 1
    assert message.join_text_parts(model_users[0].parts) == report


@pytest.mark.parametrize("source", [None, "user", "shell_completion"])
def test_interrupt_prefill_and_retraction_depend_on_input_origin(
    app_env: AppEnv, source: Literal["user", "shell_completion"] | None
) -> None:
    session_id = app_env.create_session()
    app_env.fake_llm.enqueue(message.AssistantTextDelta(content="later"), delay_s=10)
    payload = message.UserInputPayload(text="retry me", source=source)
    _call(app_env, app_env.runtime.submit, op.RunAgentOperation(session_id=session_id, input=payload))
    _wait(app_env, lambda: app_env.fake_llm.call_count == 1)
    _call(
        app_env,
        app_env.runtime.submit_and_wait,
        op.InterruptOperation(session_id=session_id, retract_unanswered_input=True),
    )
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    if source == "shell_completion":
        assert agent.consume_interrupt_prefill_text() is None
        assert not any(isinstance(item, message.RetractEntry) for item in agent.session.conversation_history)
        assert any(isinstance(item, message.UserMessage) for item in agent.session.conversation_history)
    else:
        assert agent.consume_interrupt_prefill_text() == "retry me"
        assert any(isinstance(item, message.RetractEntry) for item in agent.session.conversation_history)
        assert not any(isinstance(item, message.UserMessage) for item in agent.session.conversation_history)
