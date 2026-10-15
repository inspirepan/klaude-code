from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import pytest

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.background_task import TaskReference
from klaude_code.protocol.sub_agent import SubAgentResult

from .conftest import AppEnv


def _call(app_env: AppEnv, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    assert app_env.client.portal is not None
    return app_env.client.portal.call(partial(function, *args, **kwargs))


def test_task_api_owner_pagination_wait_and_stop_do_not_ack_model_delivery(app_env: AppEnv) -> None:
    env = app_env
    owner, foreign = env.create_session(), env.create_session()
    release = asyncio.Event()

    async def run(task_id: str, started: Callable[[str, str], Awaitable[None]]) -> SubAgentResult:
        await started("child", "operation")
        await release.wait()
        return SubAgentResult(task_result="report body", session_id="child")

    task = _call(env, env.runtime.task_manager.start_agent, owner, env.work_dir, "test task", run)
    url = f"/api/headless/sessions/{owner}/tasks"
    response = env.client.post(url, json={"action": "list"})
    assert response.status_code == 200
    assert response.json()["tasks"][0]["ref"]["owner_session_id"] == owner
    for action in ("output", "wait", "stop"):
        response = env.client.post(
            f"/api/headless/sessions/{foreign}/tasks", json={"action": action, "task_id": task.ref.task_id}
        )
        assert response.status_code == 400
    response = env.client.post(url, json={"action": "wait", "task_id": task.ref.task_id, "wait_ms": 1})
    assert response.status_code == 200 and response.json()["tasks"][0]["status"] == "running"
    _call(env, release.set)
    response = env.client.post(url, json={"action": "wait", "task_id": task.ref.task_id, "limit": 6})
    assert response.status_code == 200
    body = response.json()
    assert body["output"] == "report" and body["truncated"]
    response = env.client.post(
        url, json={"action": "output", "task_id": task.ref.task_id, "offset": body["next_offset"]}
    )
    assert response.json()["output"] == " body"
    response = env.client.post(url, json={"action": "output", "task_id": task.ref.task_id})
    assert response.json()["delivery_id"] is not None
    response = env.client.post(url, json={"action": "stop", "task_id": task.ref.task_id})
    assert response.json()["tasks"][0]["status"] == "completed"
    assert response.json()["tasks"][0]["delivered"] is False
    assert len(_call(env, env.runtime.task_manager.pending_results, owner, env.work_dir)) == 1


def test_stop_operation_stops_only_owned_agents_not_shell_root_or_peers(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    owner, peer = env.create_session(), env.create_session()
    releases = {session: asyncio.Event() for session in (owner, peer)}
    stopped: list[str] = []

    async def stop(ref: TaskReference) -> None:
        stopped.append(ref.owner_session_id)
        releases[ref.owner_session_id].set()

    monkeypatch.setattr(env.runtime.task_manager, "_stop_agent", stop)

    async def start(session: str):
        async def run(task_id: str, started: Callable[[str, str], Awaitable[None]]) -> SubAgentResult:
            await started(f"child-{session}", task_id)
            await releases[session].wait()
            return SubAgentResult(task_result="stopped report", session_id=f"child-{session}", error=True)

        return await env.runtime.task_manager.start_agent(session, env.work_dir, "background agent", run)

    _call(env, start, owner)
    _call(env, start, peer)
    shell = _call(
        env,
        env.runtime.shell_task_manager.start,
        session_id=owner,
        command="sleep 60",
        description="dev server",
        work_dir=env.work_dir,
        env=dict(os.environ),
        timeout_ms=None,
        background=True,
    )
    root_release, root_entered = asyncio.Event(), asyncio.Event()
    original_call = env.fake_llm.call

    async def blocked_root(param: llm_param.LLMCallParameter):
        root_entered.set()
        await root_release.wait()
        return await original_call(param)

    monkeypatch.setattr(env.fake_llm, "call", blocked_root)
    env.fake_llm.enqueue(message.AssistantMessage(parts=message.text_parts_from_str("root done"), stop_reason="stop"))
    try:
        brief = env.client.get(f"/api/headless/sessions/{owner}/brief").json()
        assert brief["background_agent_count"] == 1
        assert brief["background_state"] == "running"
        assert brief["state"] == "completed"
        assert env.client.post(f"/api/headless/sessions/{owner}/send", json={"text": "root work"}).status_code == 200
        _call(env, asyncio.wait_for, root_entered.wait(), 5)
        actor = env.runtime.session_registry.get_session_actor(owner)
        assert actor is not None
        root = actor.snapshot().active_root_task
        assert root is not None
        response = env.client.post(f"/api/headless/sessions/{owner}/stop")
        assert response.status_code == 200
        assert response.json()["scope"] == "sub_agents"
        assert response.json()["status"] == "completed"
        assert stopped == [owner] and not releases[peer].is_set()
        assert actor.snapshot().active_root_task == root
        tasks = env.client.post(f"/api/headless/sessions/{owner}/tasks", json={"action": "list"}).json()["tasks"]
        assert next(task for task in tasks if task["ref"]["task_id"] == shell.task_id)["status"] == "running"
        brief = env.client.get(f"/api/headless/sessions/{owner}/brief").json()
        assert brief["background_agent_count"] == 0
        assert brief["state"] == "running"
    finally:
        _call(env, root_release.set)
        _call(env, releases[peer].set)
        _call(env, env.runtime.shell_task_manager.stop_task, owner, shell.task_id)
