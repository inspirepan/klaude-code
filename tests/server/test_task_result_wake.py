"""An owner whose turn ended while its background agents run is awaiting, not idle."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Awaitable, Callable
from functools import partial
from typing import Any, cast
from uuid import uuid4

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import message, op
from klaude_code.protocol.background_task import BackgroundTaskSnapshot, TaskReference
from klaude_code.protocol.models.session_status import SessionControl
from klaude_code.protocol.peer import PeerMessage
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.session.session import Session

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

    row = env.client.get("/api/headless/sessions", params={"targets": owner}).json()["sessions"][0]
    assert row["state"] == "working"
    assert row["status"]["execution"] == "waiting_agents"
    assert row["status"]["owned"]["active_agents"] == 1

    _reply(env, "continued with the report")
    _call(env, release.set)
    _wait(env, lambda: env.fake_llm.call_count == 2 and _idle(env, owner))
    reports = _reports(env, owner)
    assert len(reports) == 1 and task_id in message.join_text_parts(reports[0].parts)
    _call(env, asyncio.sleep, 0.2)
    assert env.fake_llm.call_count == 2


def test_idle_owner_surfaces_child_question_and_keeps_pause_independent(app_env: AppEnv) -> None:
    env = app_env
    owner, child = env.create_session(), env.create_session()
    actor = env.runtime.session_registry.get_session_actor(child)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    agent.session.parent_session_id = owner
    env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[
                message.ToolCallPart(
                    call_id="question",
                    tool_name="AskUserQuestion",
                    arguments_json=json.dumps(
                        {
                            "questions": [
                                {
                                    "question": "Which?",
                                    "header": "Pick",
                                    "options": [{"label": "A", "description": "a"}, {"label": "B", "description": "b"}],
                                    "multiSelect": False,
                                }
                            ]
                        }
                    ),
                )
            ],
            stop_reason="tool_use",
            usage=usage(),
        )
    )
    _call(env, env.runtime.submit, op.RunAgentOperation(session_id=child, input=message.UserInputPayload(text="ask")))
    _wait(env, lambda: bool(actor.pending_requests_snapshot()))

    row = env.client.get("/api/headless/sessions", params={"targets": owner}).json()["sessions"][0]
    assert row["state"] == "needs_you" and row["status"]["execution"] == "none"
    assert row["status"]["attention"][0]["source_session_id"] == child
    assert row["pending_request"]["source_session_id"] == child

    _call(env, env.runtime.submit_and_wait, op.InterruptOperation(session_id=owner))
    # A queued peer is real blocked work, not an acknowledgement of the question.
    assert env.client.post(f"/api/headless/sessions/{owner}/send", json={"text": "later"}).status_code == 200
    row = env.client.get("/api/headless/sessions", params={"targets": owner}).json()["sessions"][0]
    assert {reason["kind"] for reason in row["status"]["attention"]} == {"needs_input", "paused"}

    response = env.client.post(f"/api/headless/sessions/{owner}/respond", json={"action": "deny"})
    assert response.status_code == 200
    _wait(env, lambda: not actor.pending_requests_snapshot())
    _wait(env, lambda: _idle(env, child))
    assert agent.session.runtime.last_turn is not None
    assert agent.session.runtime.last_turn.result == "interrupted"
    row = env.client.get("/api/headless/sessions", params={"targets": owner}).json()["sessions"][0]
    assert row["state"] == "needs_you"
    assert row["status"]["control"]["paused"] is True
    assert {reason["kind"] for reason in row["status"]["attention"]} == {"paused"}


def test_user_interrupt_keeps_reports_and_peer_messages_paused_until_explicit_resume(app_env: AppEnv) -> None:
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
    with env.client.websocket_connect(f"/api/sessions/{owner}/ws?replay=1") as websocket:
        while True:
            frame = websocket.receive_json()
            frames = frame if isinstance(frame, list) else [frame]
            if any(item.get("type") == "replay_complete" for item in frames):
                break
        _call(env, asyncio.sleep, 0.1)
        assert env.fake_llm.call_count == 0
        row = env.client.get("/api/headless/sessions", params={"targets": owner}).json()["sessions"][0]
        assert row["state"] == "needs_you"
        assert any(reason["kind"] == "paused" for reason in row["status"]["attention"])
    assert env.client.post(f"/api/headless/sessions/{owner}/control", json={"action": "resume"}).status_code == 200
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


@pytest.mark.parametrize("blocked", [None, "paused", "started"])
def test_restore_interactive_queue_without_attach_only_runs_unstarted_work(
    app_env: AppEnv, blocked: str | None
) -> None:
    env = app_env
    owner = env.create_session()
    _call(env, env.runtime.close_session, owner)
    session = Session.load_meta(owner, env.work_dir)
    session.set_follow_up_queue([message.QueuedUserInput(input=message.UserInputPayload(text="durable input"))])
    if blocked == "paused":
        session.runtime.control = SessionControl(paused=True, reason="user_interrupt")
        session.persist_runtime()
    elif blocked == "started":
        session.begin_turn("interrupted-turn")
    state = cast(Any, env.client.app).state.server_state
    summary = state.session_live.index.get(owner)
    assert summary is not None
    _reply(env, "recovered queue")
    _call(env, state.headless.restore, [summary])
    if blocked is None:
        _wait(env, lambda: env.fake_llm.call_count == 1 and _idle(env, owner))
        assert Session.load_meta(owner, env.work_dir).follow_up_queue == []
        assert not state.headless.is_running(owner)
    else:
        _call(env, asyncio.sleep, 0.1)
        assert env.fake_llm.call_count == 0
        restored = Session.load_meta(owner, env.work_dir)
        assert restored.follow_up_queue
        assert restored.runtime.control.paused
        if blocked == "started":
            assert restored.runtime.last_turn is not None
            assert restored.runtime.last_turn.result == "interrupted"
            assert restored.runtime.last_turn.reason == "server_restart"


def test_recovered_agent_report_needs_explicit_resume_not_a_list_or_attach(app_env: AppEnv) -> None:
    env = app_env
    session = Session.create(work_dir=env.work_dir)

    async def seed() -> None:
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("original request"))])
        await session.wait_for_flush()

    _call(env, seed)
    task_id = uuid4().hex
    task = BackgroundTaskSnapshot(
        ref=TaskReference(kind="agent", owner_session_id=session.id, task_id=task_id, run_id=task_id),
        status="running",
        description="run from before restart",
        started_at=1,
        delivery_id=f"task-result:{task_id}",
    )
    directory = Session.paths(env.work_dir).session_dir(session.id) / "background_tasks"
    directory.mkdir(exist_ok=True)
    (directory / f"{task_id}.json").write_text(task.model_dump_json())

    def restore() -> None:
        state = cast(Any, env.client.app).state.server_state
        state.session_live.index.reload()
        state.headless.restore([state.session_live.index.get(session.id)])

    _call(env, restore)

    row = env.client.get("/api/headless/sessions", params={"targets": session.id}).json()["sessions"][0]
    assert row["state"] == "needs_you"
    assert row["status"]["continuation"]["automatic"] is False
    assert "server_restart" in row["status"]["continuation"]["blocked_by"]
    with env.client.websocket_connect(f"/api/sessions/{session.id}/ws?replay=1") as websocket:
        while True:
            frame = websocket.receive_json()
            frames = frame if isinstance(frame, list) else [frame]
            if any(item.get("type") == "replay_complete" for item in frames):
                break
        _call(env, asyncio.sleep, 0.1)
        assert env.fake_llm.call_count == 0

    _reply(env, "handled the lost run")
    resumed = env.client.post(f"/api/headless/sessions/{session.id}/control", json={"action": "resume"})
    assert resumed.status_code == 200
    _wait(env, lambda: env.fake_llm.call_count == 1 and _idle(env, session.id))
    assert len(_reports(env, session.id)) == 1
    row = env.client.get("/api/headless/sessions", params={"targets": session.id}).json()["sessions"][0]
    assert row["state"] == "idle"
