"""Offline cross-layer tests with fake models and fixture-isolated HOME/credentials."""

from __future__ import annotations

import asyncio
import json

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.config.config import Config
from klaude_code.protocol import llm_param, message, op, tools
from klaude_code.protocol.background_task import TaskResponse

from .conftest import AppEnv, ScriptedLLMStream
from .test_peer_messages import _wait
from .test_task_api import _call


def test_real_agent_tools_steering_interrupt_and_stop_preserve_unowned_work(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr(AgentOperationHandler, "_schedule_prompt_suggestion", lambda *_args: None)
    monkeypatch.setattr("klaude_code.agent.runtime.sub_agent.load_config", lambda: Config(provider_list=[]))
    owner, peer = env.create_session(), env.create_session()
    actor = env.runtime.session_registry.get_session_actor(owner)
    peer_actor = env.runtime.session_registry.get_session_actor(peer)
    assert actor is not None and peer_actor is not None
    parent = actor.get_agent()
    assert parent is not None and parent.task_manager is env.runtime.task_manager
    child_started, child_cancelled = asyncio.Event(), asyncio.Event()
    peer_started, peer_cancelled = asyncio.Event(), asyncio.Event()
    wait_started, resumed = asyncio.Event(), asyncio.Event()
    release = asyncio.Event()
    parent_inputs: list[list[message.Message]] = []
    original_activity_wait = parent.pending_input_activity.wait

    async def observe_wait() -> bool:
        assert not parent.pending_input_activity.is_set()
        wait_started.set()
        return await original_activity_wait()

    monkeypatch.setattr(parent.pending_input_activity, "wait", observe_wait)

    async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
        env.fake_llm.call_count += 1
        if param.session_id != owner:
            started = peer_started if param.session_id == peer else child_started
            cancelled = peer_cancelled if param.session_id == peer else child_cancelled
            started.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            return ScriptedLLMStream(
                [message.AssistantMessage(parts=message.text_parts_from_str("background done"), stop_reason="stop")]
            )
        parent_inputs.append(list(param.input))
        if len(parent_inputs) == 1:
            call = message.ToolCallPart(
                call_id="spawn-child",
                tool_name=tools.AGENT,
                arguments_json=json.dumps({"description": "held child", "prompt": "child work"}),
            )
        elif len(parent_inputs) == 2:
            tasks = await env.runtime.task_manager.list_tasks(owner, env.work_dir)
            child = next(task for task in tasks if task.ref.kind == "agent")
            call = message.ToolCallPart(
                call_id="wait-child",
                tool_name=tools.MANAGE_TASKS,
                arguments_json=json.dumps({"action": "wait", "task_id": child.ref.task_id, "wait_ms": 300000}),
            )
        else:
            assert len(parent_inputs) == 3
            resumed.set()
            await release.wait()
            return ScriptedLLMStream(
                [message.AssistantMessage(parts=message.text_parts_from_str("parent done"), stop_reason="stop")]
            )
        return ScriptedLLMStream([message.AssistantMessage(parts=[call], stop_reason="tool_use")])

    monkeypatch.setattr(env.fake_llm, "call", scripted)
    shell = _call(
        env,
        env.runtime.shell_task_manager.start,
        session_id=owner,
        work_dir=env.work_dir,
        command="sleep 60",
        description="independent background shell",
        timeout_ms=None,
        env={},
        background=True,
    )
    try:
        _call(
            env,
            env.runtime.submit,
            op.RunAgentOperation(session_id=peer, input=message.UserInputPayload(text="independent peer")),
        )
        _call(env, asyncio.wait_for, peer_started.wait(), 5)
        peer_root = peer_actor.snapshot().active_root_task
        assert peer_root is not None
        _call(
            env,
            env.runtime.submit,
            op.RunAgentOperation(session_id=owner, input=message.UserInputPayload(text="delegate then wait")),
        )
        _call(env, asyncio.wait_for, wait_started.wait(), 5)
        _call(env, asyncio.wait_for, child_started.wait(), 5)
        tasks = _call(env, env.runtime.task_manager.list_tasks, owner, env.work_dir)
        child = next(task for task in tasks if task.ref.kind == "agent")
        assert child.status == "running" and child.ref.owner_session_id == owner
        child_actor = env.runtime.session_registry.get_session_actor(child.ref.session_id or "")
        assert child_actor is not None
        child_root = child_actor.snapshot().active_root_task
        assert child_root is not None
        spawn = next(
            item
            for item in parent.session.conversation_history
            if isinstance(item, message.ToolResultMessage) and item.call_id == "spawn-child"
        )
        assert spawn.status == "success" and child.ref.task_id in spawn.output_text
        assert "background done" not in spawn.output_text and spawn.task_metadata is None
        assert not resumed.is_set() and not child_cancelled.is_set()

        _call(
            env,
            env.runtime.submit_and_wait,
            op.FollowUpAgentOperation(session_id=owner, input=message.UserInputPayload(text="change direction")),
        )
        _call(env, asyncio.wait_for, resumed.wait(), 5)
        wait_result = next(
            item
            for item in parent_inputs[-1]
            if isinstance(item, message.ToolResultMessage) and item.call_id == "wait-child"
        )
        response = TaskResponse.model_validate_json(wait_result.output_text.splitlines()[-1])
        assert wait_result.status == "success" and response.interrupted_wait
        assert response.tasks[0].ref == child.ref and response.tasks[0].status == "running"
        assert response.delivery_id is None
        assert any(
            isinstance(item, message.UserMessage) and message.join_text_parts(item.parts) == "change direction"
            for item in parent_inputs[-1]
        )
        assert parent.follow_up_count() == 0
        assert child_actor.snapshot().active_root_task == child_root and not child_cancelled.is_set()

        assert env.client.post(f"/api/headless/sessions/{owner}/interrupt").status_code == 200
        _wait(env, lambda: actor.snapshot().is_idle)
        assert child_actor.snapshot().active_root_task == child_root and not child_cancelled.is_set()
        tasks = _call(env, env.runtime.task_manager.list_tasks, owner, env.work_dir)
        assert all(task.status == "running" for task in tasks)

        stopped = env.client.post(f"/api/headless/sessions/{owner}/stop")
        assert stopped.status_code == 200
        assert stopped.json() == {"session_id": owner, "scope": "sub_agents", "status": "completed"}
        assert child_cancelled.is_set() and child_actor.snapshot().is_idle
        tasks = _call(env, env.runtime.task_manager.list_tasks, owner, env.work_dir)
        assert next(task for task in tasks if task.ref.task_id == child.ref.task_id).status == "stopped"
        assert next(task for task in tasks if task.ref.task_id == shell.task_id).status == "running"
        assert peer_actor.snapshot().active_root_task == peer_root and not peer_cancelled.is_set()
        assert not _call(env, env.runtime.task_manager.pending_results, owner, env.work_dir)
        assert len(parent_inputs) == 3
    finally:
        _call(env, release.set)
        _call(env, env.runtime.shell_task_manager.stop_task, owner, shell.task_id)
