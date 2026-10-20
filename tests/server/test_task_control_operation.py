from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.protocol import events, llm_param, message, op
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.protocol.sub_agent import SubAgentResult
from klaude_code.server.routes import ws
from klaude_code.server.state import get_server_state_from_app

from .conftest import AppEnv
from .test_task_api import _call


def test_shared_task_operations_emit_typed_results_keep_wait_off_actor_and_never_ack(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = app_env
    owner = env.create_session()
    release = asyncio.Event()
    responses: list[events.TaskControlResultEvent] = []
    started_wait = asyncio.Event()
    original_manage = env.runtime.task_manager.manage

    async def run(task_id: str, started: Callable[[str, str], Awaitable[None]]) -> SubAgentResult:
        await started("child", "child-operation")
        await release.wait()
        return SubAgentResult(task_result="report body", session_id="child")

    async def manage(session_id, work_dir, request, *, activity=None):
        assert session_id == owner and work_dir == env.work_dir
        actor = env.runtime.session_registry.get_session_actor(owner)
        assert actor is not None
        agent = actor.get_agent()
        assert agent is not None and activity is agent.pending_input_activity
        if request.action == "wait":
            started_wait.set()
        return await original_manage(session_id, work_dir, request, activity=activity)

    monkeypatch.setattr(env.runtime.task_manager, "manage", manage)

    original_publish = env.event_bus.publish

    async def capture(event: events.Event, **kwargs: Any) -> None:
        if isinstance(event, events.TaskControlResultEvent):
            parsed = events.parse_event(events.event_type_name(event), event.model_dump(mode="json"))
            assert isinstance(parsed, events.TaskControlResultEvent)
            responses.append(parsed)
        await original_publish(event, **kwargs)

    monkeypatch.setattr(env.event_bus, "publish", capture)
    task = _call(env, env.runtime.task_manager.start_agent, owner, env.work_dir, "shared operation", run)
    shell = _call(
        env,
        env.runtime.shell_task_manager.start,
        session_id=owner,
        work_dir=env.work_dir,
        command="printf shell-output",
        description="shell output",
        timeout_ms=None,
        env={},
        background=True,
    )
    _call(env, env.runtime.shell_task_manager.wait_task, owner, shell.task_id, wait_ms=1000)

    def submit(request: TaskRequest) -> None:
        operation = op.ManageTasksOperation(session_id=owner, request=request)
        parsed = op.parse_operation(operation.model_dump(mode="json"))
        assert isinstance(parsed, op.ManageTasksOperation)
        _call(env, env.runtime.submit_and_wait, parsed)

    try:
        submit(TaskRequest(action="wait", task_id=task.ref.task_id, wait_ms=300000))
        _call(env, asyncio.wait_for, started_wait.wait(), 2)
        submit(TaskRequest(action="list"))
        assert responses[-1].request.action == "list"
        assert responses[-1].response is not None
        assert {task.ref.kind for task in responses[-1].response.tasks} == {"agent", "shell"}
        submit(TaskRequest(action="output", task_id=shell.task_id, limit=5))
        shell_response = responses[-1].response
        assert shell_response is not None and shell_response.output == "shell" and shell_response.truncated
        submit(TaskRequest(action="stop", task_id=shell.task_id))
        assert responses[-1].response is not None and responses[-1].response.tasks[0].status == "completed"
        actor = env.runtime.session_registry.get_session_actor(owner)
        assert actor is not None and actor.snapshot().active_root_task is None
        submit(TaskRequest(action="output", task_id="foreign"))
        assert responses[-1].error and responses[-1].response is None
        _call(env, release.set)

        async def wait_for_result() -> None:
            async with asyncio.timeout(3):
                while not any(event.request.action == "wait" for event in responses):
                    await asyncio.sleep(0.001)

        _call(env, wait_for_result)
        submit(TaskRequest(action="output", task_id=task.ref.task_id, limit=6))
        response = responses[-1].response
        assert response is not None and response.output == "report" and response.truncated
        submit(TaskRequest(action="output", task_id=task.ref.task_id))
        response = responses[-1].response
        assert response is not None and response.delivery_id
        assert response.tasks[0].delivered is False
        pending = _call(env, env.runtime.task_manager.pending_results, owner, env.work_dir)
        assert task.ref.task_id in {item.ref.task_id for item in pending}
        agent = actor.get_agent()
        assert agent is not None
        assert not any(
            isinstance(item, (message.UserMessage, message.AssistantMessage))
            for item in agent.session.conversation_history
        )
    finally:
        _call(env, release.set)


def test_stop_failure_is_not_a_fatal_root_error(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    env = app_env
    owner = env.create_session()
    entered, release = asyncio.Event(), asyncio.Event()
    original_call = env.fake_llm.call

    async def blocked(param: llm_param.LLMCallParameter):
        entered.set()
        await release.wait()
        return await original_call(param)

    monkeypatch.setattr(env.fake_llm, "call", blocked)
    monkeypatch.setattr(env.runtime.task_manager, "stop_sub_agents", AsyncMock(side_effect=ValueError("stop failed")))
    env.fake_llm.enqueue(message.AssistantMessage(parts=message.text_parts_from_str("root done"), stop_reason="stop"))
    emitted: list[events.Event] = []
    original_publish = env.event_bus.publish

    async def capture(event: events.Event, **kwargs: Any) -> None:
        emitted.append(event)
        await original_publish(event, **kwargs)

    monkeypatch.setattr(env.event_bus, "publish", capture)
    _call(env, env.runtime.submit, op.RunAgentOperation(session_id=owner, input=message.UserInputPayload(text="root")))
    try:
        _call(env, asyncio.wait_for, entered.wait(), 3)
        actor = env.runtime.session_registry.get_session_actor(owner)
        assert actor is not None
        root = actor.snapshot().active_root_task
        operation = op.StopSubAgentsOperation(session_id=owner)
        state = get_server_state_from_app(cast(Any, env.client.app))
        _call(env, ws._submit_stop_sub_agents, state, operation)
        receipt = next(
            event
            for event in emitted
            if isinstance(event, events.OperationFinishedEvent) and event.operation_id == operation.id
        )
        assert receipt.status == "failed" and receipt.error_message == "stop failed"
        assert actor.snapshot().active_root_task == root and root is not None
        assert not any(isinstance(event, events.ErrorEvent) for event in emitted)
    finally:
        _call(env, release.set)


@pytest.mark.parametrize("stop_type", [op.StopSubAgentsOperation, op.StopAllTasksOperation])
def test_ws_stop_dispatch_returns_before_child_stop_finishes(
    monkeypatch: pytest.MonkeyPatch, stop_type: type[op.StopSubAgentsOperation | op.StopAllTasksOperation]
) -> None:
    async def run() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        tasks: list[asyncio.Task[None]] = []

        async def submit(operation: op.Operation) -> None:
            assert isinstance(operation, stop_type)
            entered.set()
            await release.wait()

        def spawn(coro: Any) -> None:
            tasks.append(asyncio.create_task(coro))

        monkeypatch.setattr(ws, "_spawn_ws_task", spawn)
        monkeypatch.setattr(
            ws, "get_server_state_from_ws", lambda _socket: SimpleNamespace(runtime=SimpleNamespace(submit=submit))
        )
        socket = SimpleNamespace(send_json=AsyncMock())
        operation = stop_type(session_id="owner")
        try:
            await asyncio.wait_for(
                ws._handle_operation_frame(
                    "owner", ws.OpFrame(type="op", operation=operation.model_dump(mode="json")), cast(Any, socket)
                ),
                0.5,
            )
            await asyncio.wait_for(entered.wait(), 0.5)
            assert not release.is_set() and not socket.send_json.called
        finally:
            release.set()
            await asyncio.gather(*tasks)

    asyncio.run(run())


@pytest.mark.parametrize("fail_children", [False, True])
def test_stop_all_quiesces_owned_tree_and_queue_without_touching_peers(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch, fail_children: bool
) -> None:
    env = app_env
    owner, child, grandchild, peer = [env.create_session() for _ in range(4)]
    calls = 0
    release = asyncio.Event()
    entered_stop, release_stop = asyncio.Event(), asyncio.Event()
    entered_admission, release_admission = asyncio.Event(), asyncio.Event()
    delayed_run = op.RunAgentOperation(session_id=owner, input=message.UserInputPayload(text="delayed admission"))
    emitted: list[events.Event] = []
    original_publish = env.event_bus.publish
    original_stop = env.runtime.task_manager.stop_all_tasks
    original_stop_children = env.runtime.task_manager.stop_sub_agents

    async def blocked(param: llm_param.LLMCallParameter):
        nonlocal calls
        calls += 1
        await release.wait()
        raise AssertionError("Blocked model must be cancelled")

    async def capture(event: events.Event, **kwargs: Any) -> None:
        emitted.append(event)
        await original_publish(event, **kwargs)
        if isinstance(event, events.OperationAcceptedEvent) and event.operation_id == delayed_run.id:
            entered_admission.set()
            await release_admission.wait()

    async def stop_tasks(session_id: str, work_dir):
        if session_id == owner:
            entered_stop.set()
            await release_stop.wait()
        await original_stop(session_id, work_dir)

    monkeypatch.setattr(env.fake_llm, "call", blocked)
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_args: None)
    monkeypatch.setattr(env.event_bus, "publish", capture)
    monkeypatch.setattr(env.runtime.task_manager, "stop_all_tasks", stop_tasks)
    if fail_children:
        monkeypatch.setattr(
            env.runtime.task_manager, "stop_sub_agents", AsyncMock(side_effect=ValueError("child stop failed"))
        )

    async def run() -> None:
        async def wait_calls(expected: int) -> None:
            async with asyncio.timeout(3):
                while calls < expected:
                    await asyncio.sleep(0.001)

        roots: dict[str, op.RunAgentOperation] = {}
        shells = {}
        agents = {}
        for session_id in (owner, child, grandchild, peer):
            root = op.RunAgentOperation(session_id=session_id, input=message.UserInputPayload(text="work"))
            roots[session_id] = root
            await env.runtime.submit(root)
        await wait_calls(4)
        for session_id in roots:
            actor = env.runtime.session_registry.get_session_actor(session_id)
            assert actor is not None
            agent = actor.get_agent()
            assert agent is not None
            agents[session_id] = agent
            agent.follow_up(message.UserInputPayload(text="must not auto-restart"))
            shells[session_id] = await env.runtime.shell_task_manager.start(
                session_id=session_id,
                work_dir=env.work_dir,
                command="sleep 60",
                description="background",
                timeout_ms=None,
                env={},
                background=True,
            )
        agents[child].session.parent_session_id = owner
        agents[grandchild].session.parent_session_id = child

        async def track(parent: str, descendant: str) -> None:
            async def collect(task_id: str, started: Callable[[str, str], Awaitable[None]]) -> SubAgentResult:
                await started(descendant, roots[descendant].id)
                await env.runtime.wait_for(roots[descendant].id)
                return SubAgentResult(session_id=descendant, task_result="cancelled", error=True)

            await env.runtime.task_manager.start_agent(parent, env.work_dir, "owned agent", collect)

        await track(owner, child)
        await track(child, grandchild)
        for session_id in (owner, child, peer):
            await env.runtime.submit_and_wait(op.AskSideQuestionOperation(session_id=session_id, question="why?"))
        await wait_calls(7)
        operation = op.parse_operation(op.StopAllTasksOperation(session_id=owner).model_dump(mode="json"))
        stopping = asyncio.create_task(env.runtime.submit_and_wait(operation))
        admitting: asyncio.Task[str] | None = None
        try:
            await asyncio.wait_for(entered_stop.wait(), 3)
            admitting = asyncio.create_task(env.runtime.submit(delayed_run))
            await asyncio.wait_for(entered_admission.wait(), 3)
            # Work submitted during teardown must not survive its admission barrier.
            for queued in (
                op.RunAgentOperation(session_id=owner, input=message.UserInputPayload(text="racing run")),
                op.FollowUpAgentOperation(session_id=owner, input=message.UserInputPayload(text="racing follow-up")),
                op.RunBashOperation(session_id=owner, command="sleep 60"),
                op.AskSideQuestionOperation(session_id=owner, question="racing question"),
            ):
                await env.runtime.submit(queued)
            release_stop.set()
            if fail_children:
                with pytest.raises(RuntimeError, match="child stop failed"):
                    await asyncio.wait_for(stopping, 5)
            else:
                await asyncio.wait_for(stopping, 5)
            # Acceptance began during stop, but enqueue happens after it finishes.
            release_admission.set()
            await asyncio.wait_for(admitting, 3)
            await asyncio.sleep(0.05)
            receipt = next(
                event
                for event in emitted
                if isinstance(event, events.OperationFinishedEvent) and event.operation_id == operation.id
            )
            assert receipt.status == ("failed" if fail_children else "completed")
            assert not any(isinstance(event, events.ErrorEvent) for event in emitted)
            for session_id in (owner, child, grandchild):
                actor = env.runtime.session_registry.get_session_actor(session_id)
                assert actor is not None and actor.snapshot().active_root_task is None
                assert not agents[session_id].follow_up_count()
                assert agents[session_id].session.runtime.control.paused
                tasks = await env.runtime.task_manager.list_tasks(session_id, env.work_dir)
                assert all(task.status not in {"queued", "running", "stopping"} for task in tasks)
            peer_actor = env.runtime.session_registry.get_session_actor(peer)
            assert peer_actor is not None and peer_actor.snapshot().active_root_task is not None
            assert agents[peer].follow_up_count() == 1
            assert not agents[peer].session.runtime.control.paused
            assert {shell.session_id for shell in env.runtime.shell_task_manager.active_tasks()} == {peer}
            side_ends = {event.session_id for event in emitted if isinstance(event, events.SideQuestionFailedEvent)}
            assert owner in side_ends and child in side_ends and peer not in side_ends
            assert calls == 7
        finally:
            release_stop.set()
            release_admission.set()
            if admitting is not None:
                await asyncio.gather(admitting, return_exceptions=True)
            await asyncio.gather(stopping, return_exceptions=True)
            monkeypatch.setattr(env.runtime.task_manager, "stop_sub_agents", original_stop_children)
            await env.runtime.submit_and_wait(op.StopAllTasksOperation(session_id=peer))

    _call(env, run)
