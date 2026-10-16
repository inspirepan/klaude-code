"""An owner whose turn ended while its background agents run is awaiting, not idle."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import message, op
from klaude_code.protocol.peer import PeerMessage
from klaude_code.protocol.sub_agent import SubAgentResult

from .conftest import AppEnv, usage


@pytest.fixture(autouse=True)
def _disable_side_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    # Title and suggestion requests would otherwise count as LLM calls.
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.should_suggest", lambda _session: "test")


def _call(env: AppEnv, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    assert env.client.portal is not None
    return env.client.portal.call(partial(function, *args, **kwargs))


def _wait(env: AppEnv, predicate: Callable[[], bool], timeout: float = 5) -> None:
    async def poll() -> None:
        async with asyncio.timeout(timeout):
            while not predicate():
                await asyncio.sleep(0.01)

    _call(env, poll)


def _reply(env: AppEnv, text: str) -> None:
    env.fake_llm.enqueue(
        message.AssistantMessage(parts=message.text_parts_from_str(text), stop_reason="stop", usage=usage())
    )


def _idle(env: AppEnv, session_id: str) -> bool:
    actor = env.runtime.session_registry.get_session_actor(session_id)
    return actor is not None and actor.snapshot().is_idle


def _start_agent(env: AppEnv, owner: str, release: asyncio.Event) -> str:
    async def start() -> str:
        async def run(task_id: str, started: Callable[[str, str], Awaitable[None]]) -> SubAgentResult:
            await started(f"child-{task_id[:8]}", task_id)
            await release.wait()
            return SubAgentResult(task_result="child report", session_id=f"child-{task_id[:8]}")

        task = await env.runtime.task_manager.start_agent(owner, env.work_dir, "background agent", run)
        return task.ref.task_id

    return _call(env, start)


def _reports(env: AppEnv, session_id: str) -> list[message.UserMessage]:
    actor = env.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    assert agent is not None
    return [
        item
        for item in agent.session.conversation_history
        if isinstance(item, message.UserMessage) and item.source == "task_completion"
    ]


def test_finished_child_wakes_awaiting_owner_once(app_env: AppEnv) -> None:
    env = app_env
    owner = env.create_session()
    release = asyncio.Event()
    task_id = _start_agent(env, owner, release)
    _reply(env, "answered the user")
    assert env.client.post(f"/api/headless/sessions/{owner}/send", json={"text": "question"}).status_code == 200
    _wait(env, lambda: env.fake_llm.call_count == 1 and _idle(env, owner))

    _reply(env, "continued with the report")
    _call(env, release.set)
    _wait(env, lambda: env.fake_llm.call_count == 2 and _idle(env, owner))
    reports = _reports(env, owner)
    assert len(reports) == 1 and task_id in message.join_text_parts(reports[0].parts)
    _call(env, asyncio.sleep, 0.2)
    assert env.fake_llm.call_count == 2


def test_user_interrupt_pauses_wake_until_next_user_message(app_env: AppEnv) -> None:
    env = app_env
    owner = env.create_session()
    release = asyncio.Event()
    _start_agent(env, owner, release)
    _call(env, env.runtime.submit_and_wait, op.InterruptOperation(session_id=owner))
    _call(env, release.set)
    _call(env, asyncio.sleep, 0.2)
    assert env.fake_llm.call_count == 0 and _idle(env, owner)

    _reply(env, "saw the report with the user's message")
    assert env.client.post(f"/api/headless/sessions/{owner}/send", json={"text": "status?"}).status_code == 200
    _wait(env, lambda: env.fake_llm.call_count == 1 and _idle(env, owner))
    assert len(_reports(env, owner)) == 1


def test_shell_wait_returns_as_soon_as_new_input_arrives(app_env: AppEnv) -> None:
    env = app_env
    owner = env.create_session()
    start = partial(
        env.runtime.shell_task_manager.start,
        session_id=owner,
        command="sleep 60",
        description="dev server",
        work_dir=env.work_dir,
        env=dict(os.environ),
        timeout_ms=None,
        background=True,
    )
    shell = _call(env, start)
    activity = asyncio.Event()
    try:
        portal = env.client.portal
        assert portal is not None
        waiter = portal.start_task_soon(
            partial(env.runtime.shell_task_manager.wait_task, owner, shell.task_id, wait_ms=30000, activity=activity)
        )
        _call(env, asyncio.sleep, 0.05)
        assert not waiter.done()
        _call(env, activity.set)
        assert waiter.result(timeout=2).status == "running"
    finally:
        _call(env, env.runtime.shell_task_manager.stop_task, owner, shell.task_id)


def test_agent_peer_message_does_not_lift_user_stop(app_env: AppEnv) -> None:
    env = app_env
    sender, target = env.create_session(), env.create_session()
    _reply(env, "first")
    assert env.client.post(f"/api/headless/sessions/{target}/send", json={"text": "work"}).status_code == 200
    _wait(env, lambda: env.fake_llm.call_count == 1 and _idle(env, target))
    assert env.client.post(f"/api/headless/sessions/{target}/interrupt").status_code == 200
    _call(env, env.runtime.peer_control.send, sender, target, "please continue")
    _call(env, asyncio.sleep, 0.2)
    assert env.fake_llm.call_count == 1
    actor = env.runtime.session_registry.get_session_actor(target)
    agent = actor.get_agent() if actor is not None else None
    assert agent is not None
    queued = [item.peer_message for item in agent.follow_up_snapshot()]
    assert any(isinstance(peer, PeerMessage) and peer.body == "please continue" for peer in queued)


def test_finished_child_still_wakes_owner_whose_queue_holds_capped_peer_messages(app_env: AppEnv) -> None:
    env = app_env
    peer, owner = env.create_session(), env.create_session()
    release = asyncio.Event()
    _start_agent(env, owner, release)
    for index in range(3):
        _reply(env, f"reply {index}")
        _call(env, env.runtime.peer_control.send, peer, owner, f"ping {index}")
        _wait(env, lambda index=index: env.fake_llm.call_count == index + 1 and _idle(env, owner))
    _call(env, env.runtime.peer_control.send, peer, owner, "capped ping")
    _call(env, asyncio.sleep, 0.1)
    assert env.fake_llm.call_count == 3

    _reply(env, "handled the report")
    _call(env, release.set)
    _wait(env, lambda: env.fake_llm.call_count == 4 and _idle(env, owner))
    assert len(_reports(env, owner)) == 1
