from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Any, cast

import pytest

import klaude_code.agent.agent as agent_module
from klaude_code.agent.agent import Agent
from klaude_code.agent.attachments import skills
from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.control.event_bus import event_publish_context
from klaude_code.protocol import events, llm_param, message
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.protocol.models import TaskMetadataItem
from klaude_code.protocol.peer import PeerMessage, PeerReceipt
from klaude_code.server.routes import ws
from klaude_code.server.state import get_server_state_from_app
from klaude_code.session import store as session_store
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path
from klaude_code.tool.core.context import ToolContext, build_todo_context
from klaude_code.tool.peer_tool import MessagePeerTool

from .conftest import AppEnv, usage


@pytest.fixture(autouse=True)
def _disable_side_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.should_suggest", lambda _session: "test")


def _call(env: AppEnv, function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    assert env.client.portal is not None
    return env.client.portal.call(partial(function, *args, **kwargs))


def _wait(env: AppEnv, predicate: Callable[[], bool]) -> None:
    async def poll() -> None:
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(0.01)

    _call(env, poll)


def _reply(env: AppEnv, text: str) -> None:
    env.fake_llm.enqueue(
        message.AssistantMessage(parts=message.text_parts_from_str(text), stop_reason="stop", usage=usage())
    )


def _history(env: AppEnv, session_id: str) -> list[message.HistoryEvent]:
    actor = env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    _call(env, agent.session.wait_for_flush)
    return _call(env, Session.load, session_id, work_dir=env.work_dir).conversation_history


def test_guarded_panel_send_rejects_idle_and_wrong_operation_without_starting_turn(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    target = env.create_session()
    url = f"/api/headless/sessions/{target}/send-active"
    assert env.client.post(url, json={"text": "missing guard"}).status_code == 422
    rejected = env.client.post(url, json={"text": "idle message", "expected_operation_id": "old-operation"})
    assert rejected.status_code == 429 and env.fake_llm.call_count == 0
    gate, started = asyncio.Event(), asyncio.Event()
    original = env.fake_llm.call

    async def hold_first(param: llm_param.LLMCallParameter):
        if not started.is_set():
            started.set()
            await gate.wait()
        return await original(param)

    monkeypatch.setattr(env.fake_llm, "call", hold_first)
    _reply(env, "first response")
    _reply(env, "peer response")
    assert env.client.post(f"/api/headless/sessions/{target}/send", json={"text": "start"}).status_code == 200
    _wait(env, started.is_set)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    active = actor.snapshot().active_root_task
    assert active is not None
    try:
        rejected = env.client.post(url, json={"text": "wrong run", "expected_operation_id": "old-operation"})
        assert rejected.status_code == 429 and agent.follow_up_count() == 0
        accepted = env.client.post(
            url, json={"text": "/stop is peer data", "expected_operation_id": active.operation_id}
        )
        assert accepted.status_code == 200 and accepted.json()["accepted"]
        pending = agent.follow_up_snapshot()
        assert len(pending) == 1 and pending[0].source == "peer_message"
        assert pending[0].peer_message is not None and pending[0].peer_message.body == "/stop is peer data"
        assert pending[0].peer_message.sender_session_id is None
    finally:
        _call(env, gate.set)
    _wait(env, lambda: actor.snapshot().is_idle)
    calls = env.fake_llm.call_count
    rejected = env.client.post(url, json={"text": "after finish", "expected_operation_id": active.operation_id})
    assert rejected.status_code == 429 and env.fake_llm.call_count == calls


@pytest.mark.parametrize("via_tool", [False, True], ids=["peer-port", "message-peer-tool"])
def test_busy_batch_keeps_two_senders_plaintext_and_history_tape_replay(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, via_tool: bool
) -> None:
    env = app_env
    sender_a, sender_b, target = (env.create_session() for _ in range(3))
    secret = env.work_dir / "private.txt"
    secret.write_text("FILE-MUST-NOT-BE-ATTACHED")
    inputs: list[list[message.Message]] = []
    taped: list[events.UserMessageEvent] = []
    resolved_skills: list[str] = []

    def resolve_skill(_session: Session, name: str):
        resolved_skills.append(name)
        return None

    monkeypatch.setattr(skills, "resolve_skill_for_input", resolve_skill)
    gate = asyncio.Event()
    original = env.fake_llm.call

    async def capture(param: llm_param.LLMCallParameter):
        inputs.append(list(param.input))
        if len(inputs) == 1:
            await gate.wait()
        else:
            state = get_server_state_from_app(cast(Any, env.client.app))
            assert state.tapes is not None
            cut = state.tapes.cut(target)
            assert cut is not None
            taped.extend(item.event for item in cut.envelopes if isinstance(item.event, events.UserMessageEvent))
        return await original(param)

    monkeypatch.setattr(env.fake_llm, "call", capture)
    _reply(env, "first step")
    _reply(env, "latest assistant is not a peer reply")
    assert env.client.post(f"/api/headless/sessions/{target}/send", json={"text": "start"}).status_code == 200
    _wait(env, lambda: len(inputs) == 1)
    body = f"/compact /skill:peer-only @{secret} end"
    receipts: list[PeerReceipt] = []
    for sender in (sender_a, sender_b):
        if via_tool:
            sender_actor = env.runtime.session_registry.get_session_actor(sender)
            assert sender_actor is not None
            sender_agent = sender_actor.get_agent()
            assert sender_agent is not None and sender_agent.peer_control is env.runtime.peer_control
            context = ToolContext(
                file_tracker=sender_agent.session.file_tracker,
                todo_context=build_todo_context(sender_agent.session),
                session_id=sender,
                work_dir=env.work_dir,
                peer_control=sender_agent.peer_control,
            )
            result = _call(env, MessagePeerTool.call, json.dumps({"target": target, "body": body}), context)
            assert result.status == "success"
            assert f"Target: {target}" in result.output_text and "Accepted: true" in result.output_text
            assert "Delivery: queued" in result.output_text
            message_id = result.output_text.splitlines()[0].removeprefix("Message: ")
            receipts.append(PeerReceipt(message_id=message_id, target=target))
        else:
            receipts.append(_call(env, env.runtime.peer_control.send, sender, target, body))
    assert all(receipt.accepted and receipt.target == target for receipt in receipts)
    assert all("assistant" not in receipt.model_dump() for receipt in receipts)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    target_agent = actor.get_agent()
    assert target_agent is not None and target_agent.follow_up_count() == 2
    assert len(inputs) == 1
    _call(env, gate.set)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    _wait(env, lambda: len(inputs) == 2 and actor.snapshot().is_idle)
    history = _history(env, target)
    peers = [item for item in history if isinstance(item, message.UserMessage) and item.peer_message is not None]
    assert [item.peer_message.sender_session_id for item in peers if item.peer_message is not None] == [
        None,
        sender_a,
        sender_b,
    ]
    assert [item.id for item in peers[1:]] == [receipt.message_id for receipt in receipts]
    assert all(item.source == "peer_message" for item in peers)
    model_peers = [
        item
        for item in inputs[1]
        if isinstance(item, message.UserMessage) and item.id in {peer.id for peer in peers[1:]}
    ]
    assert model_peers == peers[1:]
    assert all(item.peer_message is not None and item.peer_message.body == body for item in model_peers)
    assert all(body in message.join_text_parts(item.parts) for item in model_peers)
    assert not any("FILE-MUST-NOT-BE-ATTACHED" in item.model_dump_json() for batch in inputs for item in batch)
    assert resolved_skills == []
    agent = actor.get_agent()
    assert agent is not None and str(secret) not in agent.session.file_tracker
    for sender in (sender_a, sender_b):
        assert not _history(env, sender)
    loaded = _call(env, Session.load, target, work_dir=env.work_dir)
    replay = [item for item in loaded.get_history_item() if isinstance(item, events.UserMessageEvent)]
    assert [item.peer_message for item in replay] == [item.peer_message for item in peers]
    assert [item.peer_message for item in taped] == [item.peer_message for item in peers]


def test_idle_explicit_reply_and_external_identity_cannot_be_forged(app_env: AppEnv) -> None:
    env = app_env
    sender, target = env.create_session(), env.create_session()
    _reply(env, "not automatically sent back")
    receipt = _call(env, env.runtime.peer_control.send, sender, target, "question")
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    _wait(env, lambda: env.fake_llm.call_count == 1 and actor.snapshot().is_idle)
    assert not _history(env, sender)
    _reply(env, "reply received")
    explicit = _call(env, env.runtime.peer_control.send, target, sender, "answer", receipt.message_id)
    _wait(env, lambda: env.fake_llm.call_count == 2)
    peer = next(item.peer_message for item in _history(env, sender) if isinstance(item, message.UserMessage))
    assert peer is not None and peer.reply_to == receipt.message_id and peer.id == explicit.message_id
    _reply(env, "external received")
    response = env.client.post(
        f"/api/headless/sessions/{target}/send",
        json={"text": "external", "sender": "operator", "sender_session_id": sender, "message_id": "external-id"},
    )
    assert response.status_code == 200
    assert response.json()["message_id"] == "external-id"
    _wait(env, lambda: env.fake_llm.call_count == 3)
    external = next(
        item for item in _history(env, target) if isinstance(item, message.UserMessage) and item.id == "external-id"
    )
    assert external.source == "peer_message"
    assert external.peer_message is not None and external.peer_message.sender_session_id is None


def test_peer_dedup_rate_and_queue_limits_are_explicit(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    headless = state.headless
    assert headless is not None
    monkeypatch.setattr(headless, "_schedule_follow_up_drain", lambda *_args: None)

    async def check() -> None:
        first = PeerMessage(id="stable", sender_session_id="a", recipient=target, body="one")
        receipt = await headless.deliver_peer(first, env.work_dir)
        assert await headless.deliver_peer(first, env.work_dir) == receipt
        with pytest.raises(ValueError, match="different content or sender"):
            await headless.deliver_peer(first.model_copy(update={"sender_session_id": "b"}), env.work_dir)
        with pytest.raises(ValueError, match="Duplicate"):
            await headless.deliver_peer(first.model_copy(update={"id": "another"}), env.work_dir)
        await headless.deliver_peer(
            first.model_copy(update={"id": "other-sender", "sender_session_id": "b"}), env.work_dir
        )
        for index in range(9):
            await headless.deliver_peer(
                PeerMessage(sender_session_id="a", recipient=target, body=f"a-{index}"), env.work_dir
            )
        with pytest.raises(ValueError, match="rate limit"):
            await headless.deliver_peer(
                PeerMessage(sender_session_id="a", recipient=target, body="rate rejected"), env.work_dir
            )
        for index in range(39):
            await headless.deliver_peer(
                PeerMessage(sender_session_id=f"sender-{index}", recipient=target, body="same body"), env.work_dir
            )
        with pytest.raises(ValueError, match="queue is full"):
            await headless.deliver_peer(
                PeerMessage(sender_session_id="extra", recipient=target, body="overflow"), env.work_dir
            )
        actor = env.runtime.session_registry.get_session_actor(target)
        assert actor is not None and actor.get_agent() is not None
        agent = actor.get_agent()
        assert agent is not None and agent.follow_up_count() == 50
        loaded = Session.load(target, work_dir=env.work_dir)
        assert len(loaded.follow_up_queue) == 50
        original_flush = Session.wait_for_flush
        fail_once = True

        async def flush(session: Session) -> None:
            nonlocal fail_once
            if session is agent.session and fail_once:
                fail_once = False
                raise OSError("flush failed")
            await original_flush(session)

        monkeypatch.setattr(Session, "wait_for_flush", flush)
        with pytest.raises(OSError, match="flush failed"):
            async for _event in agent.inject_pending_inputs():
                pass
        assert agent.follow_up_count() == 50
        async for _event in agent.inject_pending_inputs():
            pass
        assert agent.follow_up_count() == 0
        assert await headless.deliver_peer(first, env.work_dir) == receipt
        assert agent.follow_up_count() == 0
        loaded = Session.load(target, work_dir=env.work_dir)
        assert (
            sum(isinstance(item, message.UserMessage) and item.id == "stable" for item in loaded.conversation_history)
            == 1
        )
        assert not loaded.follow_up_queue
        first_index = next(
            index
            for index, item in enumerate(agent.session.conversation_history)
            if isinstance(item, message.UserMessage) and item.id == first.id
        )
        agent.session.append_history(
            [
                message.RetractEntry(
                    retracted_text=first.input_text(),
                    retracted_line=agent.session.line_index_of(first_index),
                )
            ]
        )
        await agent.session.wait_for_flush()
        reloaded = Session.load(target, work_dir=env.work_dir)
        assert not any(
            isinstance(item, message.UserMessage) and item.id == first.id for item in reloaded.conversation_history
        )
        restored = Agent(reloaded, agent.profile, peer_control=agent.peer_control)
        actor.set_agent(restored)
        assert await headless.deliver_peer(first, env.work_dir) == receipt
        assert restored.follow_up_count() == 0

    _call(env, check)


def test_discovery_excludes_self_and_other_workspaces_and_rejects_ambiguous_target(app_env: AppEnv) -> None:
    env = app_env
    sender, target = env.create_session(), env.create_session()
    other_dir = env.work_dir / "other"
    other_dir.mkdir()
    foreign = env.create_session(other_dir)
    peers = _call(env, env.runtime.peer_control.list, sender, env.work_dir)
    assert target in {peer.session_id for peer in peers}
    assert sender not in {peer.session_id for peer in peers}
    assert foreign not in {peer.session_id for peer in peers}
    # The sender is never its own target, so ambiguity needs two other sessions.
    twin = env.create_session()
    for session_id in (sender, target, twin):
        actor = env.runtime.session_registry.get_session_actor(session_id)
        assert actor is not None
        agent = actor.get_agent()
        assert agent is not None
        agent.session.name = "same-name"
        _call(env, get_store_for_path(env.work_dir).update_meta, session_id, {"name": "same-name"})
    with pytest.raises(ValueError, match="ambiguous"):
        _call(env, env.runtime.peer_control.send, sender, "same-name", "not sent")


def test_metadata_write_failure_returns_500_without_false_acceptance_and_retry_recovers(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    headless = state.headless
    assert headless is not None
    monkeypatch.setattr(headless, "_schedule_follow_up_drain", lambda *_args: None)
    original = session_store._write_json_dict_atomic
    failed = True

    def write(path: Path, data: dict[str, Any], suffix: str) -> None:
        if failed and path == get_store_for_path(env.work_dir).paths.meta_file(target):
            raise OSError("atomic metadata failure")
        original(path, data, suffix)

    monkeypatch.setattr(session_store, "_write_json_dict_atomic", write)
    payload = {"text": "must survive", "message_id": "retry-after-meta-failure"}
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    for _ in range(2):
        response = env.client.post(f"/api/headless/sessions/{target}/send", json=payload)
        assert response.status_code == 500
        assert "accepted" not in response.json()
        assert agent.follow_up_records() == ()
        assert not agent.pending_input_activity.is_set()
        assert not agent.session.follow_up_queue
        assert not Session.load_meta(target, env.work_dir).follow_up_queue
    failed = False
    response = env.client.post(f"/api/headless/sessions/{target}/send", json=payload)
    assert response.status_code == 200 and response.json()["accepted"] is True
    restored = Agent(Session.load(target, env.work_dir), agent.profile)
    actor.set_agent(restored)
    assert len(restored.follow_up_records()) == 1
    retried = env.client.post(f"/api/headless/sessions/{target}/send", json=payload).json()
    for key in ("session_id", "message_id", "target", "accepted", "mode"):
        assert retried[key] == response.json()[key]

    async def admit() -> None:
        async for _ in restored.inject_pending_inputs():
            pass

    _call(env, admit)
    loaded = Session.load(target, env.work_dir)
    assert [item.id for item in loaded.conversation_history if isinstance(item, message.UserMessage)] == [
        payload["message_id"]
    ]
    assert not loaded.follow_up_queue


@pytest.mark.parametrize("admitting", [False, True])
def test_peer_id_conflicting_with_operator_queue_is_rejected_even_during_admission(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, admitting: bool
) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    assert state.headless is not None
    monkeypatch.setattr(state.headless, "_schedule_follow_up_drain", lambda *_args: None)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    original_agent = actor.get_agent()
    assert original_agent is not None
    queued = message.QueuedUserInput(id="operator-id", input=message.UserInputPayload(text="operator input"))
    original_agent.session.set_follow_up_queue([queued])
    agent = Agent(original_agent.session, original_agent.profile)
    actor.set_agent(agent)
    entered, release = asyncio.Event(), asyncio.Event()
    freeze = agent_module.freeze_user_input_for_history

    async def blocked_freeze(*args: Any, **kwargs: Any) -> message.UserInputPayload:
        entered.set()
        await release.wait()
        return await freeze(*args, **kwargs)

    monkeypatch.setattr(agent_module, "freeze_user_input_for_history", blocked_freeze)

    async def inject() -> None:
        async for _ in agent.inject_pending_inputs():
            pass

    async def begin() -> asyncio.Task[None]:
        task = asyncio.create_task(inject())
        await entered.wait()
        return task

    task = _call(env, begin) if admitting else None
    try:
        response = env.client.post(
            f"/api/headless/sessions/{target}/send", json={"text": "peer", "message_id": queued.id}
        )
        assert response.status_code == 429
        assert "different content or sender" in response.json()["detail"]
        assert agent.follow_up_records() == (queued,)
        assert Session.load_meta(target, env.work_dir).follow_up_queue == [queued]
    finally:
        _call(env, release.set)
        if task is not None:

            async def finish() -> None:
                await task

            _call(env, finish)


def test_external_task_prefix_id_survives_api_disk_restore_and_admission(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    assert state.headless is not None
    monkeypatch.setattr(state.headless, "_schedule_follow_up_drain", lambda *_args: None)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    metadata = TaskMetadataItem(background_task_id="exact-collision")

    async def seed() -> None:
        agent.session.append_history([metadata], deduplicate_background_tasks=True)
        await agent.session.wait_for_background_task_flush()

    _call(env, seed)
    payload = {"text": "must not disappear", "message_id": "task:exact-collision"}
    response = env.client.post(f"/api/headless/sessions/{target}/send", json=payload)
    assert response.status_code == 200 and response.json()["accepted"] is True
    restored = Agent(Session.load(target, env.work_dir), agent.profile)
    actor.set_agent(restored)

    async def admit_and_retry_metadata() -> None:
        async for _ in restored.inject_pending_inputs():
            pass
        assert [restored.session.line_index_of(i) for i in range(2)] == [0, 1]
        restored.session.append_history([metadata], deduplicate_background_tasks=True)
        await restored.session.wait_for_background_task_flush()

    _call(env, admit_and_retry_metadata)
    loaded = Session.load(target, env.work_dir)
    peers = [item for item in loaded.conversation_history if isinstance(item, message.UserMessage)]
    assert len(peers) == 1 and peers[0].id == payload["message_id"]
    assert peers[0].peer_message is not None and peers[0].peer_message.body == payload["text"]
    assert sum(isinstance(item, TaskMetadataItem) for item in loaded.conversation_history) == 1
    assert not loaded.follow_up_queue
    retried = env.client.post(f"/api/headless/sessions/{target}/send", json=payload).json()
    for key in ("session_id", "message_id", "target", "accepted", "mode"):
        assert retried[key] == response.json()[key]
    assert retried["state"] == "idle" and retried["pending"] is False


@pytest.mark.parametrize("complete_first", [False, True], ids=["peer-before-completion", "completion-before-peer"])
def test_internal_delivery_ids_rejected_before_acceptance_in_both_orders(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, complete_first: bool
) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    assert state.headless is not None
    monkeypatch.setattr(state.headless, "_schedule_follow_up_drain", lambda *_args: None)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None

    async def start() -> str:
        task = await env.runtime.shell_task_manager.start(
            session_id=target,
            work_dir=env.work_dir,
            command="while [ ! -f release-task ]; do sleep 0.01; done; printf actual-result",
            description="delivery collision",
            env={},
            timeout_ms=10000,
            background=True,
        )
        return task.task_id

    task_id = _call(env, start)
    delivery_id = f"task-result:{task_id}"

    async def complete_and_inject() -> None:
        (env.work_dir / "release-task").touch()
        await env.runtime.task_manager.manage(target, env.work_dir, TaskRequest(action="wait", task_id=task_id))
        _ = [event async for event in agent.inject_pending_inputs()]

    if complete_first:
        _call(env, complete_and_inject)
    response = env.client.post(
        f"/api/headless/sessions/{target}/send", json={"text": "must reject", "message_id": delivery_id}
    )
    assert response.status_code == 422 and "reserved" in response.text
    assert "accepted" not in response.json()
    assert not agent.follow_up_records()
    assert not Session.load_meta(target, env.work_dir).follow_up_queue
    with pytest.raises(ValueError, match="reserved"):
        PeerMessage(id=delivery_id, recipient=target, body="native construction")
    # Model copies and legacy disk objects cannot bypass runtime admission either.
    bypassed = PeerMessage(recipient=target, body="bypass").model_copy(update={"id": delivery_id})
    with pytest.raises(ValueError, match="reserved"):
        _call(env, state.headless.deliver_peer, bypassed, env.work_dir)

    payload = {"text": "ordinary peer", "message_id": "normal-retry-id"}
    accepted = env.client.post(f"/api/headless/sessions/{target}/send", json=payload)
    assert accepted.status_code == 200 and accepted.json()["accepted"]
    _call(env, complete_and_inject)
    restored = Agent(Session.load(target, env.work_dir), agent.profile, task_manager=env.runtime.task_manager)
    actor.set_agent(restored)
    retried = env.client.post(f"/api/headless/sessions/{target}/send", json=payload).json()
    for key in ("session_id", "message_id", "target", "accepted", "mode"):
        assert retried[key] == accepted.json()[key]
    users = [item for item in _history(env, target) if isinstance(item, message.UserMessage)]
    assert [(item.id, item.source) for item in users] == [
        (delivery_id, "task_completion"),
        ("normal-retry-id", "peer_message"),
    ]
    assert "actual-result" in message.join_text_parts(users[0].parts)
    assert _call(env, env.runtime.task_manager.pending_results, target, env.work_dir) == []


@pytest.mark.parametrize("peer", [False, True], ids=["operator-input-id", "legacy-peer-id"])
def test_legacy_reserved_queue_id_remains_diagnostic_after_restart(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, peer: bool
) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    assert state.headless is not None
    monkeypatch.setattr(state.headless, "_schedule_follow_up_drain", lambda *_args: None)
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None

    async def check() -> None:
        task = await env.runtime.shell_task_manager.start(
            session_id=target,
            work_dir=env.work_dir,
            command="printf still-pending",
            description="legacy collision",
            env={},
            timeout_ms=10000,
            background=True,
        )
        await env.runtime.task_manager.manage(target, env.work_dir, TaskRequest(action="wait", task_id=task.task_id))
        delivery_id = f"task-result:{task.task_id}"
        legacy = PeerMessage.model_construct(id=delivery_id, recipient=target, body="legacy peer") if peer else None
        queued = message.QueuedUserInput(
            id=delivery_id,
            input=message.UserInputPayload(
                text="legacy input", source="peer_message" if peer else None, peer_message=legacy
            ),
        )
        agent.session.set_follow_up_queue([queued])
        await agent.session.wait_for_flush()
        restored = Agent(Session.load(target, env.work_dir), agent.profile, task_manager=env.runtime.task_manager)
        assert restored.follow_up_records() == (queued,)
        with pytest.raises(ValueError, match="reserved"):
            _ = [event async for event in restored.inject_pending_inputs()]
        assert restored.follow_up_records() == (queued,)
        assert Session.load_meta(target, env.work_dir).follow_up_queue == [queued]
        pending = await env.runtime.task_manager.pending_results(target, env.work_dir)
        assert len(pending) == 1 and pending[0].delivery_id == delivery_id and not pending[0].delivered

    _call(env, check)


class CaptureSocket:
    def __init__(self) -> None:
        self.frames: list[dict[str, Any]] = []

    async def send_json(self, payload: Any) -> None:
        self.frames.append(payload)


def test_background_task_snapshot_is_available_without_live_completion(app_env: AppEnv) -> None:
    env = app_env
    target = env.create_session()
    state = get_server_state_from_app(cast(Any, env.client.app))
    socket = CaptureSocket()

    async def complete_shell() -> str:
        task = await env.runtime.shell_task_manager.start(
            session_id=target,
            work_dir=env.work_dir,
            command="printf replay-output",
            description="snapshot",
            env={},
            timeout_ms=None,
            background=True,
        )
        await env.runtime.shell_task_manager.wait_task(target, task.task_id)
        return task.task_id

    task_id = _call(env, complete_shell)
    cutoffs = _call(env, ws._send_background_task_snapshots, target, env.work_dir, socket, state=state)
    assert target in cutoffs
    assert socket.frames[0]["event_type"] == "background.tasks.updated"
    tasks = socket.frames[0]["event"]["tasks"]
    assert len(tasks) == 1 and tasks[0]["ref"]["task_id"] == task_id
    assert tasks[0]["ref"]["owner_session_id"] == target
    assert tasks[0]["status"] == "completed" and tasks[0]["delivered"] is False
    assert env.fake_llm.call_count == 0


def test_peer_delivery_never_stamps_recipient_events_with_sender_turn_ids(app_env: AppEnv) -> None:
    """A delivery runs inside the sender's turn; clients follow task IDs, so a
    borrowed one would stream the sender's turn into the recipient's view."""
    env = app_env
    sender, target = env.create_session(), env.create_session()
    _reply(env, "answered")

    async def deliver_and_collect() -> list[events.EventEnvelope]:
        seen: list[events.EventEnvelope] = []
        subscription = env.event_bus.subscribe(target)

        async def collect() -> None:
            async for envelope in subscription:
                seen.append(envelope)
                if isinstance(envelope.event, events.TaskFinishEvent):
                    return

        collector = asyncio.create_task(collect())
        with event_publish_context(operation_id="sender-op", task_id="sender-task", causation_id="sender-cause"):
            await env.runtime.peer_control.send(sender, target, "question")
        async with asyncio.timeout(5):
            await collector
        return seen

    recipient = _call(env, deliver_and_collect)
    assert any(isinstance(item.event, events.TaskStartEvent) for item in recipient)
    assert all(item.task_id != "sender-task" for item in recipient)
    assert all(item.operation_id != "sender-op" and item.causation_id != "sender-cause" for item in recipient)


def test_agent_messages_start_at_most_three_turns_between_user_inputs(app_env: AppEnv) -> None:
    env = app_env
    sender, target = env.create_session(), env.create_session()
    actor = env.runtime.session_registry.get_session_actor(target)
    assert actor is not None
    for index in range(3):
        _reply(env, f"reply {index}")
        _call(env, env.runtime.peer_control.send, sender, target, f"ping {index}")
        _wait(env, lambda index=index: env.fake_llm.call_count == index + 1 and actor.snapshot().is_idle)
    _call(env, env.runtime.peer_control.send, sender, target, "ping 3")
    _call(env, asyncio.sleep, 0.2)
    assert env.fake_llm.call_count == 3
    agent = actor.get_agent()
    assert agent is not None and agent.follow_up_count() == 1

    _reply(env, "user turn sees the queued ping")
    assert env.client.post(f"/api/headless/sessions/{target}/send", json={"text": "what happened?"}).status_code == 200
    _wait(env, lambda: env.fake_llm.call_count == 4 and actor.snapshot().is_idle)
    assert agent.follow_up_count() == 0
    bodies = [
        item.peer_message.body
        for item in _history(env, target)
        if isinstance(item, message.UserMessage) and item.peer_message is not None
    ]
    assert bodies[-2:] == ["ping 3", "what happened?"]
