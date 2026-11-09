"""Exercise native Agent/Tasks/Message tools through the owned local runtime."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.app.peer_endpoint import call_endpoint
from klaude_code.config import Config
from klaude_code.protocol import events, llm_param, message, op, tools, user_interaction
from klaude_code.protocol.background_task import TaskRequest
from klaude_code.protocol.peer import PeerMessage
from klaude_code.tui.client.local import LocalRuntimeClient
from tests.fake_llm import FakeLLMClient, ScriptedLLMStream


def reply(text: str) -> ScriptedLLMStream:
    return ScriptedLLMStream([message.AssistantMessage(parts=message.text_parts_from_str(text), stop_reason="stop")])


def tool(name: str, arguments: dict[str, Any], call_id: str) -> ScriptedLLMStream:
    return ScriptedLLMStream(
        [
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(
                        call_id=call_id,
                        tool_name=name,
                        arguments_json=json.dumps(arguments),
                    )
                ],
                stop_reason="tool_use",
            )
        ]
    )


async def eventually(predicate: Callable[[], bool]) -> None:
    async with asyncio.timeout(5):
        while not predicate():
            await asyncio.sleep(0.01)


class LocalGroup:
    def __init__(self, directory: Path, fake: FakeLLMClient):
        self.directory = directory
        self.fake = fake
        self.clients: list[LocalRuntimeClient] = []
        self.events: dict[str, list[events.EventEnvelope]] = {}

    async def create(self, *, work_dir: Path | None = None, session_id: str | None = None) -> LocalRuntimeClient:
        captured: list[events.EventEnvelope] = []

        async def consume(envelope: events.EventEnvelope) -> None:
            captured.append(envelope)

        client = LocalRuntimeClient(session_id, on_envelope=consume, work_dir=work_dir or self.directory)
        self.clients.append(client)
        await client.start()
        client.start_display()
        await client.wait_for_display_idle()
        self.events[client.session_id] = captured
        return client


@pytest.fixture
def local_group(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fake = FakeLLMClient()
    monkeypatch.setattr(
        "klaude_code.app.runtime.build_llm_clients", lambda *_a, **_k: LLMClients(main=fake, main_model_alias="fake")
    )
    monkeypatch.setattr(
        "klaude_code.agent.runtime.agent_ops.build_llm_clients",
        lambda *_a, **_k: LLMClients(main=fake, main_model_alias="fake"),
    )
    monkeypatch.setattr("klaude_code.agent.runtime.llm.clone_llm_client", lambda value: value)
    monkeypatch.setattr("klaude_code.agent.runtime.sub_agent.load_config", lambda: Config(provider_list=[]))
    monkeypatch.setattr(AgentOperationHandler, "_schedule_session_title_refresh", lambda *_a: None)
    monkeypatch.setattr(AgentOperationHandler, "_schedule_prompt_suggestion", lambda *_a: None)

    @asynccontextmanager
    async def group() -> AsyncIterator[LocalGroup]:
        env = LocalGroup(tmp_path, fake)
        try:
            yield env
        finally:
            for client in reversed(env.clients):
                await client.close()

    return group


def reports(client: LocalRuntimeClient) -> list[message.UserMessage]:
    return [
        item
        for item in client.command_agent().session.conversation_history
        if isinstance(item, message.UserMessage) and item.source == "task_completion"
    ]


def test_native_agent_is_async_reports_once_and_replays_without_execution(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            release, started = asyncio.Event(), asyncio.Event()
            inputs: list[list[message.Message]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                if param.session_id != owner.session_id:
                    started.set()
                    await release.wait()
                    return reply("child report")
                inputs.append(list(param.input))
                if len(inputs) == 1:
                    return tool(tools.AGENT, {"description": "held child", "prompt": "child work"}, "launch")
                return reply("report acknowledged" if reports(owner) else "main answer")

            monkeypatch.setattr(env.fake, "call", scripted)
            first = op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="delegate"))
            await owner.submit(first)
            await asyncio.wait_for(owner.wait_for(first.id), 5)
            await asyncio.wait_for(started.wait(), 5)
            tasks = (await owner.manage_tasks(TaskRequest(action="list"))).tasks
            assert len(tasks) == 1 and tasks[0].status == "running"
            child = tasks[0]
            assert child.ref.owner_session_id == owner.session_id and child.activity is not None
            assert owner._scheduler is not None
            assert owner._scheduler.session_status(owner.session_id).execution == "waiting_agents"
            launch = next(
                item
                for item in owner.command_agent().session.conversation_history
                if isinstance(item, message.ToolResultMessage) and item.call_id == "launch"
            )
            assert child.ref.task_id in launch.output_text and "child report" not in launch.output_text
            assert launch.task_metadata is None

            await owner.submit_and_wait(
                op.RunAgentOperation(
                    session_id=owner.session_id, input=message.UserInputPayload(text="another question")
                )
            )
            assert not release.is_set() and len(inputs) == 3
            assert (await owner.manage_tasks(TaskRequest(action="list"))).tasks[0].status == "running"
            release.set()
            await eventually(lambda: len(inputs) == 4 and len(reports(owner)) == 1 and not owner.has_running_tasks())
            await owner.wait_for_display_idle()
            assert child.ref.task_id in message.join_text_parts(reports(owner)[0].parts)
            task = (await owner.manage_tasks(TaskRequest(action="list"))).tasks[0]
            assert task.status == "completed" and task.delivered
            await asyncio.sleep(0.1)
            assert len(inputs) == 4
            session_id = owner.session_id
            await owner.close()
            resumed = await env.create(session_id=session_id)
            replay = [
                envelope.event
                for envelope in env.events[session_id]
                if isinstance(envelope.event, events.ReplayHistoryEvent)
            ]
            assert len(replay) == 1
            assert any(
                isinstance(event, events.TaskStartEvent) and event.parent_session_id == session_id
                for event in replay[0].events
            )
            assert "child report" in str(replay[0])
            assert len(inputs) == 4
            assert resumed.session_info().is_replay_snapshot

    asyncio.run(run())


def test_child_question_routes_through_root_and_paused_reports_wait_for_resume(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            inputs: list[list[message.Message]] = []
            child_calls = 0

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                nonlocal child_calls
                if param.session_id != owner.session_id:
                    child_calls += 1
                    if child_calls == 1:
                        return tool(
                            tools.ASK_USER_QUESTION,
                            {
                                "questions": [
                                    {
                                        "header": "Pick",
                                        "question": "Which?",
                                        "multiSelect": False,
                                        "options": [
                                            {"label": "A", "description": "first"},
                                            {"label": "B", "description": "second"},
                                        ],
                                    }
                                ]
                            },
                            "question",
                        )
                    return reply("child answered")
                inputs.append(list(param.input))
                if len(inputs) == 1:
                    return tool(tools.AGENT, {"description": "questioning child", "prompt": "ask a question"}, "launch")
                return reply("owner answer")

            monkeypatch.setattr(env.fake, "call", scripted)
            await owner.submit_and_wait(
                op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="delegate"))
            )
            request = await asyncio.wait_for(owner.interaction_requests().get(), 5)
            assert request.session_id != owner.session_id
            endpoint = owner._endpoint
            assert endpoint is not None
            snapshot = await endpoint._dispatch({"method": "snapshot", "session_id": owner.session_id})
            assert snapshot["state"] == "needs_you"
            assert snapshot["pending_request"]["source_session_id"] == request.session_id
            await owner.submit_and_wait(op.InterruptOperation(session_id=owner.session_id))
            await endpoint._dispatch(
                {
                    "method": "deliver",
                    "message": PeerMessage(recipient=owner.session_id, body="queued peer data").model_dump(),
                }
            )
            await endpoint._dispatch(
                {"method": "respond", "session_id": owner.session_id, "response": {"action": "option", "option": 1}}
            )
            await eventually(
                lambda: child_calls == 2
                and not owner.components.runtime.session_registry.get_session_actor(
                    request.session_id
                ).pending_requests_snapshot()
            )
            await asyncio.sleep(0.1)
            assert len(inputs) == 2 and not reports(owner)
            assert owner.interaction_closed_event(request).is_set()
            await endpoint._dispatch({"method": "control", "session_id": owner.session_id, "action": "resume"})
            await eventually(lambda: len(reports(owner)) == 1 and not owner.has_running_tasks())
            assert len(inputs) == 3
            assert any(isinstance(item, message.UserMessage) and item.source == "peer_message" for item in inputs[-1])
            assert owner.command_agent().steering_count() == 0

    asyncio.run(run())


def test_native_task_wait_steering_interrupt_and_stop_keep_other_owner_running(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner, peer = await env.create(), await env.create()
            child_started, child_cancelled = asyncio.Event(), asyncio.Event()
            peer_started, peer_cancelled = asyncio.Event(), asyncio.Event()
            waiting, resumed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
            parent_inputs: list[list[message.Message]] = []
            parent = owner.command_agent()
            original_wait = parent.pending_input_activity.wait

            async def observe_wait() -> bool:
                waiting.set()
                return await original_wait()

            monkeypatch.setattr(parent.pending_input_activity, "wait", observe_wait)

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                if param.session_id != owner.session_id:
                    started = peer_started if param.session_id == peer.session_id else child_started
                    cancelled = peer_cancelled if param.session_id == peer.session_id else child_cancelled
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                    return reply("background done")
                parent_inputs.append(list(param.input))
                if len(parent_inputs) == 1:
                    return tool(tools.AGENT, {"description": "held child", "prompt": "child work"}, "launch")
                if len(parent_inputs) == 2:
                    child = next(
                        task
                        for task in (await owner.manage_tasks(TaskRequest(action="list"))).tasks
                        if task.ref.kind == "agent"
                    )
                    return tool(
                        tools.MANAGE_TASKS, {"action": "wait", "task_id": child.ref.task_id, "wait_ms": 300000}, "wait"
                    )
                resumed.set()
                await release.wait()
                return reply("main done")

            monkeypatch.setattr(env.fake, "call", scripted)
            runtime = owner.components.runtime
            shell = await runtime.shell_task_manager.start(
                session_id=owner.session_id,
                work_dir=env.directory,
                command="sleep 60",
                description="owned shell",
                timeout_ms=None,
                env={},
                background=True,
            )
            peer_op = op.RunAgentOperation(session_id=peer.session_id, input=message.UserInputPayload(text="peer work"))
            await peer.submit(peer_op)
            await asyncio.wait_for(peer_started.wait(), 5)
            root_op = op.RunAgentOperation(
                session_id=owner.session_id, input=message.UserInputPayload(text="delegate then wait")
            )
            await owner.submit(root_op)
            await asyncio.wait_for(waiting.wait(), 5)
            await asyncio.wait_for(child_started.wait(), 5)
            child = next(
                task
                for task in (await owner.manage_tasks(TaskRequest(action="list"))).tasks
                if task.ref.kind == "agent"
            )
            child_actor = runtime.session_registry.get_session_actor(child.ref.session_id or "")
            assert child_actor is not None
            original_child = child_actor.snapshot().active_root_task
            await owner.submit_and_wait(
                op.QueueFollowUpOperation(
                    session_id=owner.session_id, input=message.UserInputPayload(text="after the current task")
                )
            )
            await asyncio.sleep(0.05)
            assert len(parent_inputs) == 2 and not resumed.is_set()
            await owner.submit_and_wait(
                op.SteerAgentOperation(
                    session_id=owner.session_id, input=message.UserInputPayload(text="change direction")
                )
            )
            await asyncio.wait_for(resumed.wait(), 5)
            wait_result = next(
                item
                for item in parent_inputs[-1]
                if isinstance(item, message.ToolResultMessage) and item.call_id == "wait"
            )
            assert "interrupted-wait; still-running" in wait_result.output_text
            assert wait_result.task_delivery_id is None
            assert any(
                isinstance(item, message.UserMessage) and message.join_text_parts(item.parts) == "change direction"
                for item in parent_inputs[-1]
            )
            assert child_actor.snapshot().active_root_task == original_child and not child_cancelled.is_set()
            await owner.submit_and_wait(
                op.InterruptOperation(session_id=owner.session_id, expected_operation_id=root_op.id)
            )
            await owner.wait_for(root_op.id)
            assert parent.follow_up_count() == 1
            await owner.submit_and_wait(
                op.SteerAgentOperation(
                    session_id=owner.session_id, input=message.UserInputPayload(text="pending steering")
                )
            )
            assert not child_cancelled.is_set()
            assert runtime.shell_task_manager.has_running_tasks()
            assert owner._endpoint is not None
            await owner._endpoint._dispatch({"method": "stop-children", "session_id": owner.session_id})
            assert child_cancelled.is_set() and child_actor.snapshot().is_idle
            assert (await runtime.shell_task_manager.list_tasks(owner.session_id))[0].status == "running"
            await owner.submit_and_wait(op.StopAllTasksOperation(session_id=owner.session_id))
            assert parent.steering_count() == parent.follow_up_count() == 0
            assert (await runtime.shell_task_manager.list_tasks(owner.session_id))[0].status == "stopped"
            assert not peer_cancelled.is_set() and peer.is_running()
            assert not await runtime.task_manager.pending_results(owner.session_id, env.directory)
            assert len(parent_inputs) == 3
            assert shell.task_id in {
                task.ref.task_id for task in (await owner.manage_tasks(TaskRequest(action="list"))).tasks
            }
            release.set()
            await peer.wait_for(peer_op.id)

    asyncio.run(run())


@pytest.mark.parametrize("headless", [False, True])
def test_cancelled_question_retains_follow_up_without_blocking_later_steering(
    local_group, monkeypatch: pytest.MonkeyPatch, headless: bool
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            agent = owner.command_agent()
            if headless:
                agent.session.spawn_kind = "headless"
                agent.session.ensure_meta_exists()
            inputs: list[list[str]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                inputs.append(
                    [
                        message.join_text_parts(item.parts)
                        for item in param.input
                        if isinstance(item, message.UserMessage)
                    ]
                )
                if len(inputs) == 1:
                    return tool(
                        tools.ASK_USER_QUESTION,
                        {
                            "questions": [
                                {
                                    "header": "Pick",
                                    "question": "Which?",
                                    "multiSelect": False,
                                    "options": [
                                        {"label": "A", "description": "first"},
                                        {"label": "B", "description": "second"},
                                    ],
                                }
                            ]
                        },
                        "question",
                    )
                return reply("done")

            monkeypatch.setattr(env.fake, "call", scripted)
            initial = op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="initial"))
            await owner.submit(initial)
            request = await asyncio.wait_for(owner.interaction_requests().get(), 5)
            await owner.submit_and_wait(
                op.QueueFollowUpOperation(session_id=owner.session_id, input=message.UserInputPayload(text="later"))
            )
            await owner.submit_and_wait(
                op.UserInteractionRespondOperation(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
                )
            )
            await owner.wait_for(initial.id)
            await asyncio.sleep(0.1)
            assert inputs == [["initial"]] and agent.follow_up_count() == 1
            assert owner._scheduler is not None
            assert not owner._scheduler.has_live_steering(owner.session_id)
            await owner.submit_and_wait(
                op.SteerAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="steering"))
            )
            await eventually(lambda: len(inputs) == 3 and not owner.has_running_tasks())
            assert inputs == [["initial"], ["initial", "steering"], ["initial", "steering", "later"]]
            assert agent.follow_up_count() == agent.steering_count() == 0

    asyncio.run(run())


@pytest.mark.parametrize("resume_steering", [False, True])
def test_interrupt_retains_follow_up_until_user_resumes(
    local_group, monkeypatch: pytest.MonkeyPatch, resume_steering: bool
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            agent = owner.command_agent()
            started = asyncio.Event()
            inputs: list[list[str]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                inputs.append(
                    [
                        message.join_text_parts(item.parts)
                        for item in param.input
                        if isinstance(item, message.UserMessage)
                    ]
                )
                if len(inputs) == 1:
                    started.set()
                    await asyncio.Event().wait()
                return reply("done")

            monkeypatch.setattr(env.fake, "call", scripted)
            initial = op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="initial"))
            await owner.submit(initial)
            await asyncio.wait_for(started.wait(), 5)
            await owner.submit_and_wait(
                op.QueueFollowUpOperation(session_id=owner.session_id, input=message.UserInputPayload(text="later"))
            )
            await owner.submit_and_wait(
                op.InterruptOperation(
                    session_id=owner.session_id,
                    expected_operation_id=initial.id,
                    retract_unanswered_input=True,
                    resume_follow_ups=resume_steering,
                )
            )
            await owner.wait_for(initial.id)
            await asyncio.sleep(0.1)
            assert inputs == [["initial"]] and agent.follow_up_count() == 1
            await owner.submit_and_wait(
                op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="resume"))
            )
            await eventually(lambda: len(inputs) == 3 and not owner.has_running_tasks())
            assert inputs == [["initial"], ["initial", "resume"], ["initial", "resume", "later"]]
            assert agent.follow_up_count() == agent.steering_count() == 0

    asyncio.run(run())


@pytest.mark.parametrize("headless", [False, True])
def test_idle_follow_up_operation_drains_and_remaining_inputs_share_one_run(
    local_group, monkeypatch: pytest.MonkeyPatch, headless: bool
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            agent = owner.command_agent()
            if headless:
                agent.session.spawn_kind = "headless"
                agent.session.ensure_meta_exists()
            started, release = asyncio.Event(), asyncio.Event()
            inputs: list[list[str]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                inputs.append(
                    [
                        message.join_text_parts(item.parts)
                        for item in param.input
                        if isinstance(item, message.UserMessage)
                    ]
                )
                if len(inputs) == 1:
                    started.set()
                    await release.wait()
                return reply("done")

            monkeypatch.setattr(env.fake, "call", scripted)
            await owner.submit_and_wait(
                op.QueueFollowUpOperation(session_id=owner.session_id, input=message.UserInputPayload(text="first"))
            )
            await asyncio.wait_for(started.wait(), 5)
            await owner.submit_and_wait(
                op.QueueFollowUpOperation(session_id=owner.session_id, input=message.UserInputPayload(text="second"))
            )
            assert inputs == [["first"]]
            release.set()
            await eventually(lambda: len(inputs) == 2 and not owner.has_running_tasks())
            await owner.wait_for_display_idle()
            assert inputs == [["first"], ["first", "second"]]
            assert agent.follow_up_count() == 0
            captured = [envelope.event for envelope in env.events[owner.session_id]]
            assert len([event for event in captured if isinstance(event, events.TaskStartEvent)]) == 1
            assert len([event for event in captured if isinstance(event, events.TaskFinishEvent)]) == 1

    asyncio.run(run())


@pytest.mark.parametrize("headless", [False, True])
def test_follow_up_submitted_after_natural_end_check_drains_after_teardown(
    local_group, monkeypatch: pytest.MonkeyPatch, headless: bool
) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            agent = owner.command_agent()
            if headless:
                agent.session.spawn_kind = "headless"
                agent.session.ensure_meta_exists()
            original_run = agent.run_task
            queued = False
            inputs: list[list[str]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                inputs.append(
                    [
                        message.join_text_parts(item.parts)
                        for item in param.input
                        if isinstance(item, message.UserMessage)
                    ]
                )
                return reply("done")

            async def run_with_late_input(
                payload: message.UserInputPayload, **kwargs: Any
            ) -> AsyncGenerator[events.Event]:
                nonlocal queued
                async for event in original_run(payload, **kwargs):
                    if isinstance(event, events.TaskFinishEvent) and not queued:
                        queued = True
                        for text in ("late one", "late two"):
                            await owner.submit_and_wait(
                                op.QueueFollowUpOperation(
                                    session_id=owner.session_id, input=message.UserInputPayload(text=text)
                                )
                            )
                        assert inputs == [["initial"]]
                    yield event

            monkeypatch.setattr(env.fake, "call", scripted)
            monkeypatch.setattr(agent, "run_task", run_with_late_input)
            initial = op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="initial"))
            await owner.submit_and_wait(initial)
            await eventually(lambda: len(inputs) == 3 and not owner.has_running_tasks())
            await owner.wait_for_display_idle()
            assert inputs == [["initial"], ["initial", "late one"], ["initial", "late one", "late two"]]
            assert agent.follow_up_count() == 0
            captured = [envelope.event for envelope in env.events[owner.session_id]]
            assert len([event for event in captured if isinstance(event, events.TaskStartEvent)]) == 2
            assert len([event for event in captured if isinstance(event, events.TaskFinishEvent)]) == 2

    asyncio.run(run())


def test_busy_peer_delivery_is_safe_boundary_data_and_idle_peer_turns_are_capped(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async with local_group() as env:
            source, target = await env.create(), await env.create()
            started, release = asyncio.Event(), asyncio.Event()
            requests: list[list[message.Message]] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                assert param.session_id == target.session_id
                requests.append(list(param.input))
                if len(requests) == 1:
                    started.set()
                    await release.wait()
                return reply("done")

            monkeypatch.setattr(env.fake, "call", scripted)
            operation = op.RunAgentOperation(
                session_id=target.session_id, input=message.UserInputPayload(text="original")
            )
            await target.submit(operation)
            await started.wait()
            endpoint = source._endpoint
            assert endpoint is not None
            receipt = await endpoint.send_peer(source.session_id, target.session_id, "while busy", None)
            assert receipt.mode == "queued"
            assert not any(
                isinstance(item, message.UserMessage) and item.source == "peer_message" for item in requests[0]
            )
            release.set()
            await eventually(lambda: len(requests) == 2 and not target.has_running_tasks())
            peer_input = next(
                item for item in requests[-1] if isinstance(item, message.UserMessage) and item.source == "peer_message"
            )
            assert (
                peer_input.peer_message is not None and peer_input.peer_message.sender_session_id == source.session_id
            )
            for index in range(4):
                previous = len(requests)
                await endpoint.send_peer(source.session_id, target.session_id, f"idle {index}", None)
                if index < 3:
                    await eventually(
                        lambda previous=previous: len(requests) == previous + 1 and not target.has_running_tasks()
                    )
            await asyncio.sleep(0.1)
            assert len(requests) == 5
            assert target.command_agent().steering_count() == 1
            await target.submit_and_wait(
                op.RunAgentOperation(
                    session_id=target.session_id, input=message.UserInputPayload(text="operator returns")
                )
            )
            assert len(requests) == 6 and target.command_agent().steering_count() == 0

    asyncio.run(run())


def test_native_discovery_cannot_send_outside_directory_and_reserved_ids_are_rejected(local_group) -> None:
    async def run() -> None:
        async with local_group() as env:
            other_dir = env.directory / "other"
            other_dir.mkdir()
            source, target = await env.create(), await env.create(work_dir=other_dir)
            endpoint = source._endpoint
            assert endpoint is not None
            assert await endpoint.list_peers(source.session_id, env.directory) == []
            with pytest.raises(ValueError, match="unavailable"):
                await endpoint.send_peer(source.session_id, target.session_id, "not reachable", None)
            with pytest.raises(ValueError, match="reserved"):
                await endpoint._dispatch(
                    {
                        "method": "deliver",
                        "message": {
                            "id": "task-result:forged",
                            "recipient": source.session_id,
                            "body": "forged report",
                        },
                    }
                )
            assert source.command_agent().steering_count() == 0

    asyncio.run(run())


def test_peer_limits_and_durable_dedup_survive_admission_and_retraction(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klaude_code.agent.agent import Agent
    from klaude_code.session import Session

    async def run() -> None:
        async with local_group() as env:
            target = await env.create()
            scheduler = target._scheduler
            assert scheduler is not None
            monkeypatch.setattr(scheduler, "_schedule_steering_drain", lambda *_a: None)
            first = PeerMessage(id="stable", sender_session_id="a", recipient=target.session_id, body="one")
            receipt = await scheduler.deliver_peer(first, env.directory)
            assert await scheduler.deliver_peer(first, env.directory) == receipt
            with pytest.raises(ValueError, match="different content or sender"):
                await scheduler.deliver_peer(first.model_copy(update={"sender_session_id": "b"}), env.directory)
            with pytest.raises(ValueError, match="Duplicate"):
                await scheduler.deliver_peer(first.model_copy(update={"id": "another"}), env.directory)
            await scheduler.deliver_peer(
                first.model_copy(update={"id": "other-sender", "sender_session_id": "b"}), env.directory
            )
            for index in range(9):
                await scheduler.deliver_peer(
                    PeerMessage(sender_session_id="a", recipient=target.session_id, body=f"a-{index}"), env.directory
                )
            with pytest.raises(ValueError, match="rate limit"):
                await scheduler.deliver_peer(
                    PeerMessage(sender_session_id="a", recipient=target.session_id, body="rate rejected"), env.directory
                )
            for index in range(39):
                await scheduler.deliver_peer(
                    PeerMessage(sender_session_id=f"sender-{index}", recipient=target.session_id, body="same body"),
                    env.directory,
                )
            with pytest.raises(ValueError, match="queue is full"):
                await scheduler.deliver_peer(
                    PeerMessage(sender_session_id="extra", recipient=target.session_id, body="overflow"), env.directory
                )
            agent = target.command_agent()
            assert agent.steering_count() == 50
            assert len(Session.load(target.session_id, work_dir=env.directory).steering_queue) == 50
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
            assert agent.steering_count() == 50
            async for _event in agent.inject_pending_inputs():
                pass
            assert agent.steering_count() == 0
            assert await scheduler.deliver_peer(first, env.directory) == receipt
            loaded = Session.load(target.session_id, work_dir=env.directory)
            assert (
                sum(
                    isinstance(item, message.UserMessage) and item.id == first.id
                    for item in loaded.conversation_history
                )
                == 1
            )
            assert not loaded.steering_queue
            first_index = next(
                index
                for index, item in enumerate(agent.session.conversation_history)
                if isinstance(item, message.UserMessage) and item.id == first.id
            )
            agent.session.append_history(
                [
                    message.RetractEntry(
                        retracted_text=first.input_text(), retracted_line=agent.session.line_index_of(first_index)
                    )
                ]
            )
            await agent.session.wait_for_flush()
            restored = Agent(
                Session.load(target.session_id, work_dir=env.directory), agent.profile, peer_control=agent.peer_control
            )
            target.components.runtime.session_registry.get_session_actor(target.session_id).set_agent(restored)
            assert await scheduler.deliver_peer(first, env.directory) == receipt
            assert restored.steering_count() == 0

    asyncio.run(run())


def test_ipc_does_not_ack_failed_metadata_write_and_retry_is_durable(
    local_group, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klaude_code.session import Session, store
    from klaude_code.session.store_registry import get_store_for_path

    async def run() -> None:
        async with local_group() as env:
            target = await env.create()
            await target.submit_and_wait(op.InterruptOperation(session_id=target.session_id))
            assert target._scheduler is not None and target._endpoint is not None
            monkeypatch.setattr(target._scheduler, "_schedule_steering_drain", lambda *_a: None)
            original = store._write_json_dict_atomic
            failed = True

            def write(path: Path, data: dict[str, Any], suffix: str) -> None:
                if failed and path == get_store_for_path(env.directory).paths.meta_file(target.session_id):
                    raise OSError("atomic metadata failure")
                original(path, data, suffix)

            monkeypatch.setattr(store, "_write_json_dict_atomic", write)
            peer = PeerMessage(id="durable-retry", recipient=target.session_id, body="must survive")
            for _ in range(2):
                with pytest.raises(ValueError, match="atomic metadata failure"):
                    await call_endpoint(target._endpoint.record, "deliver", message=peer.model_dump(mode="json"))
                assert not target.command_agent().steering_records()
                assert not Session.load_meta(target.session_id, env.directory).steering_queue
            failed = False
            receipt = await call_endpoint(target._endpoint.record, "deliver", message=peer.model_dump(mode="json"))
            assert receipt["accepted"]
            session_id = target.session_id
            await target.close()
            resumed = await env.create(session_id=session_id)
            assert resumed._scheduler is not None and resumed._endpoint is not None
            monkeypatch.setattr(resumed._scheduler, "_schedule_steering_drain", lambda *_a: None)
            assert len(resumed.command_agent().steering_records()) == 1
            assert (
                await call_endpoint(resumed._endpoint.record, "deliver", message=peer.model_dump(mode="json"))
                == receipt
            )
            assert len(resumed.command_agent().steering_records()) == 1

    asyncio.run(run())


def test_control_failures_reach_local_and_ipc_callers(local_group, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()

            async def fail(_operation: op.Operation) -> None:
                raise RuntimeError("stop failed")

            monkeypatch.setattr(owner.components.runtime._operation_dispatcher, "handle_stop_sub_agents", fail)
            with pytest.raises(RuntimeError, match="failed"):
                await owner.submit_and_wait(op.StopSubAgentsOperation(session_id=owner.session_id))
            assert owner._endpoint is not None
            with pytest.raises(ValueError, match="failed"):
                await call_endpoint(owner._endpoint.record, "stop-children", session_id=owner.session_id)

    asyncio.run(run())


def test_task_panel_message_requires_owned_running_operation(local_group, monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    async def run() -> None:
        async with local_group() as env:
            owner, peer = await env.create(), await env.create()
            roots = {owner.session_id, peer.session_id}
            calls: dict[str, int] = {}
            release = asyncio.Event()

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                if param.session_id not in roots:
                    await release.wait()
                    return reply("child done")
                calls[param.session_id] = calls.get(param.session_id, 0) + 1
                if calls[param.session_id] == 1:
                    return tool(tools.AGENT, {"description": "held child", "prompt": "work"}, "launch")
                return reply("parent done")

            monkeypatch.setattr(env.fake, "call", scripted)
            for root in (owner, peer):
                await root.submit_and_wait(
                    op.RunAgentOperation(session_id=root.session_id, input=message.UserInputPayload(text="delegate"))
                )
            own_tasks = await owner.manage_tasks(TaskRequest(action="list"))
            own = own_tasks.tasks[0]
            other = (await peer.manage_tasks(TaskRequest(action="list"))).tasks[0]
            with pytest.raises(ValueError, match="no longer running"):
                await owner.send_task_message(other.ref.task_id, "wrong owner")
            receipt = await owner.send_task_message(own.ref.task_id, "operator direction")
            assert receipt.mode == "queued"
            child_actor = owner.components.runtime.session_registry.get_session_actor(own.ref.session_id or "")
            assert child_actor is not None and child_actor.get_agent().steering_count() == 1
            await owner.submit_and_wait(op.StopSubAgentsOperation(session_id=owner.session_id))
            after_stop = child_actor.get_agent().steering_count()
            monkeypatch.setattr(owner, "manage_tasks", AsyncMock(return_value=own_tasks))
            with pytest.raises(ValueError, match="no longer running"):
                await owner.send_task_message(own.ref.task_id, "stale selection")
            assert child_actor.get_agent().steering_count() == after_stop
            assert (await peer.manage_tasks(TaskRequest(action="list"))).tasks[0].status == "running"
            release.set()

    asyncio.run(run())


def test_headless_child_cannot_ask_user_question(local_group, monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        async with local_group() as env:
            owner = await env.create()
            session = owner.command_agent().session
            session.spawn_kind = "headless"
            session.unattended = True
            parent_calls, child_calls = 0, 0
            answers: list[str] = []

            async def scripted(param: llm_param.LLMCallParameter) -> ScriptedLLMStream:
                nonlocal parent_calls, child_calls
                if param.session_id == owner.session_id:
                    parent_calls += 1
                    if parent_calls == 1:
                        return tool(tools.AGENT, {"description": "questioning child", "prompt": "ask"}, "launch")
                    return reply("done")
                child_calls += 1
                if child_calls == 1:
                    return tool(
                        tools.ASK_USER_QUESTION,
                        {
                            "questions": [
                                {
                                    "header": "Pick",
                                    "question": "Which?",
                                    "multiSelect": False,
                                    "options": [
                                        {"label": "A", "description": "first"},
                                        {"label": "B", "description": "second"},
                                    ],
                                }
                            ]
                        },
                        "ask",
                    )
                answers.extend(
                    item.output_text
                    for item in param.input
                    if isinstance(item, message.ToolResultMessage) and item.call_id == "ask"
                )
                return reply("child done")

            monkeypatch.setattr(env.fake, "call", scripted)
            await owner.submit_and_wait(
                op.RunAgentOperation(session_id=owner.session_id, input=message.UserInputPayload(text="delegate"))
            )
            await eventually(lambda: bool(answers) and len(reports(owner)) == 1 and not owner.has_running_tasks())
            assert child_calls == 2
            assert answers == ["Tool AskUserQuestion not exists"]
            assert owner.interaction_requests().empty()

    asyncio.run(run())
