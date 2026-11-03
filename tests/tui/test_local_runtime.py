from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.protocol import events, message, op
from klaude_code.protocol.message import UserInputPayload
from klaude_code.session import Session
from klaude_code.tui.client.local import LocalRuntimeClient
from tests.fake_llm import FakeLLMClient


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLMClient:
    client = FakeLLMClient()
    clients = LLMClients(main=client, main_model_alias="fake")
    monkeypatch.setattr("klaude_code.app.runtime.build_llm_clients", lambda *_args, **_kwargs: clients)
    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.build_llm_clients", lambda *_args, **_kwargs: clients)
    monkeypatch.setattr("klaude_code.agent.runtime.llm.clone_llm_client", lambda value: value)
    return client


def test_local_turn_replay_and_shutdown(fake_llm: FakeLLMClient, tmp_path: Path) -> None:
    async def run() -> None:
        received: list[events.Event] = []

        async def consume(envelope: events.EventEnvelope) -> None:
            received.append(envelope.event)

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        fake_llm.enqueue(message.AssistantMessage(parts=[message.TextPart(text="local answer")]))
        await client.submit_and_wait(
            op.RunAgentOperation(session_id=client.session_id, input=UserInputPayload(text="hello"))
        )
        await client.wait_for_display_idle()
        session_id = client.session_id
        await client.close()
        assert any(isinstance(event, events.WelcomeEvent) for event in received)
        assert any(isinstance(event, events.TaskFinishEvent) for event in received)
        assert Session.load(session_id, work_dir=tmp_path).messages_count > 0
        assert fake_llm.call_count >= 1

        replayed: list[events.Event] = []

        async def replay(envelope: events.EventEnvelope) -> None:
            replayed.append(envelope.event)

        resumed = LocalRuntimeClient(session_id, on_envelope=replay, work_dir=tmp_path, vanilla=True)
        await resumed.start()
        resumed.start_display()
        await resumed.wait_for_display_idle()
        assert any(isinstance(event, events.ReplayHistoryEvent) for event in replayed)
        before = fake_llm.call_count
        await resumed.close()
        assert fake_llm.call_count == before

    asyncio.run(run())


def test_second_executor_rejected_and_lease_released(fake_llm: FakeLLMClient, tmp_path: Path) -> None:
    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        first = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await first.start()
        second = LocalRuntimeClient(first.session_id, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        try:
            with pytest.raises(ValueError, match="active in another"):
                await second.start()
        finally:
            await first.close()
        third = LocalRuntimeClient(first.session_id, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await third.start()
        await third.close()

    asyncio.run(run())


def test_initialization_failure_closes_components(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail(_self: LocalRuntimeClient) -> None:
        raise RuntimeError("init failed")

    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        monkeypatch.setattr(LocalRuntimeClient, "_initialize_session", fail)
        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path)
        with pytest.raises(RuntimeError, match="init failed"):
            await client.start()
        assert client._components is None
        await client.close()

    asyncio.run(run())


def test_local_tool_interaction_round_trip(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import json
    from unittest.mock import AsyncMock

    from klaude_code.protocol import user_interaction

    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.generate_session_title", AsyncMock(return_value=None))

    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path)
        await client.start()
        client.start_display()
        try:
            fake_llm.enqueue(
                message.AssistantMessage(
                    parts=[
                        message.ToolCallPart(
                            call_id="ask",
                            tool_name="AskUserQuestion",
                            arguments_json=json.dumps(
                                {
                                    "questions": [
                                        {
                                            "header": "Pick",
                                            "question": "Which option?",
                                            "multiSelect": False,
                                            "options": [
                                                {"label": "A", "description": "First"},
                                                {"label": "B", "description": "Second"},
                                            ],
                                        }
                                    ]
                                }
                            ),
                        )
                    ],
                    stop_reason="tool_use",
                )
            )
            fake_llm.enqueue(message.AssistantMessage(parts=[message.TextPart(text="answered")]))
            operation = op.RunAgentOperation(session_id=client.session_id, input=UserInputPayload(text="ask me"))
            await client.submit(operation)
            request = await asyncio.wait_for(client.interaction_requests().get(), 3)
            assert isinstance(request.payload, user_interaction.AskUserQuestionRequestPayload)
            question = request.payload.questions[0]
            await client.submit_and_wait(
                op.UserInteractionRespondOperation(
                    session_id=request.session_id,
                    request_id=request.request_id,
                    response=user_interaction.UserInteractionResponse(
                        status="submitted",
                        payload=user_interaction.AskUserQuestionResponsePayload(
                            answers=[
                                user_interaction.AskUserQuestionAnswer(
                                    question_id=question.id, selected_option_ids=[question.options[0].id]
                                ),
                            ]
                        ),
                    ),
                )
            )
            await asyncio.wait_for(client.wait_for(operation.id), 3)
            await client.wait_for_display_idle()
            assert client.interaction_closed_event(request).is_set()
            assert "answered" in str(client.command_agent().session.conversation_history)
        finally:
            await client.close()

    asyncio.run(run())


def test_local_background_shell_blocks_switch_and_stops_on_exit(fake_llm: FakeLLMClient, tmp_path: Path) -> None:
    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        manager = client.components.runtime.shell_task_manager
        task = await manager.start(
            session_id=client.session_id,
            work_dir=tmp_path,
            command="sleep 60",
            description="background",
            timeout_ms=None,
            env={},
            background=True,
        )
        try:
            assert client.has_running_tasks()
            with pytest.raises(ValueError, match="/stop"):
                await client.create_session()
        finally:
            await client.close()
        snapshots = await manager.list_tasks(client.session_id)
        assert next(item for item in snapshots if item.task_id == task.task_id).status == "stopped"
        assert not manager.has_running_tasks()

    asyncio.run(run())


def test_restore_interrupted_turn_preserves_queue_without_execution(fake_llm: FakeLLMClient, tmp_path: Path) -> None:
    from klaude_code.protocol.message import QueuedUserInput
    from klaude_code.protocol.models.session_status import SessionActiveTurn

    async def run() -> None:
        saved = Session.create(work_dir=tmp_path)
        saved.ensure_meta_exists()
        saved.runtime.active_turn = SessionActiveTurn(id="interrupted-turn", started=True)
        saved.persist_runtime()
        saved.set_follow_up_queue([QueuedUserInput(input=UserInputPayload(text="pending input"))])

        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        client = LocalRuntimeClient(saved.id, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        await client.wait_for_display_idle()
        try:
            session = client.command_agent().session
            assert session.runtime.active_turn is None
            assert session.runtime.last_turn is not None and session.runtime.last_turn.result == "interrupted"
            assert session.runtime.control.paused
            assert client.follow_up_texts() == ("pending input",)
            assert fake_llm.call_count == 0
        finally:
            await client.close()

    asyncio.run(run())


def test_local_interrupt_retracts_input_and_finishes_operation(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.generate_session_title", AsyncMock(return_value=None))

    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        fake_llm.enqueue(message.AssistantTextDelta(content="slow"), delay_s=60)
        operation = op.RunAgentOperation(session_id=client.session_id, input=UserInputPayload(text="interrupt me"))
        try:
            await client.submit(operation)
            for _ in range(100):
                if fake_llm.call_count:
                    break
                await asyncio.sleep(0.01)
            assert fake_llm.call_count == 1
            await client.submit_and_wait(
                op.InterruptOperation(
                    session_id=client.session_id,
                    expected_operation_id=operation.id,
                    retract_unanswered_input=True,
                )
            )
            await asyncio.wait_for(client.wait_for(operation.id), 3)
            await client.wait_for_display_idle()
            assert client.consume_interrupt_prefill() == "interrupt me"
            assert not client.is_running()
        finally:
            await client.close()

    asyncio.run(run())


def test_cleanup_failure_still_stops_runtime_and_releases_lease(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run() -> None:
        async def consume(_envelope: events.EventEnvelope) -> None:
            pass

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        components = client.components
        original_stop = components.config_watcher.stop

        def broken_stop() -> None:
            original_stop()
            raise RuntimeError("watcher cleanup failed")

        monkeypatch.setattr(components.config_watcher, "stop", broken_stop)
        with pytest.raises(ExceptionGroup, match="cleanup failed"):
            await client.close()
        assert components.runtime._stopped
        assert not components.runtime._session_leases
        assert components.display_task.done()
        assert components.idle_reclaim_task.done()

    asyncio.run(run())


def test_buffered_initial_statuses_keep_replay_boundary_after_live_turn(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import AsyncMock

    from klaude_code.protocol.models.session_status import SessionTurnResult

    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.generate_session_title", AsyncMock(return_value=None))

    async def run() -> None:
        saved = Session.create(work_dir=tmp_path)
        saved.runtime.last_turn = SessionTurnResult(id="old-turn", result="succeeded")
        saved.ensure_meta_exists()
        saved.persist_runtime()
        await saved.wait_for_flush()
        seen: list[events.EventEnvelope] = []

        async def consume(envelope: events.EventEnvelope) -> None:
            seen.append(envelope)

        client = LocalRuntimeClient(saved.id, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        boundary = client.session_info().replay_through_event_seq
        assert boundary > 0 and client.session_info().is_replay_snapshot
        try:
            fake_llm.enqueue(message.AssistantMessage(parts=message.text_parts_from_str("new result")))
            await client.submit_and_wait(
                op.RunAgentOperation(session_id=client.session_id, input=UserInputPayload(text="new turn"))
            )
            await client.components.wait_for_display_idle()
            assert not client.session_info().is_replay_snapshot
            assert client.session_info().replay_through_event_seq == boundary
            client.start_display()
            await client.wait_for_display_idle()
            statuses = [item for item in seen if isinstance(item.event, events.SessionStatusEvent)]
            initial = [item for item in statuses if item.event_seq <= boundary]
            live = [item for item in statuses if item.event_seq > boundary]
            assert initial and live
            assert all(
                isinstance(item.event, events.SessionStatusEvent)
                and (item.event.status.last_turn is None or item.event.status.last_turn.id == "old-turn")
                for item in initial
            )
            assert any(
                isinstance(item.event, events.SessionStatusEvent)
                and item.event.status.last_turn
                and item.event.status.last_turn.id != "old-turn"
                for item in live
            )
        finally:
            await client.close()

    asyncio.run(run())


def test_switch_to_preloaded_rewind_session_emits_welcome_and_replay_once(
    fake_llm: FakeLLMClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from klaude_code.app.session_lease import SessionLease

    monkeypatch.setattr("klaude_code.agent.runtime.agent_ops.get_startup_update_summary", lambda: None)

    async def run() -> None:
        seen: list[events.Event] = []

        async def consume(envelope: events.EventEnvelope) -> None:
            seen.append(envelope.event)

        client = LocalRuntimeClient(None, on_envelope=consume, work_dir=tmp_path, vanilla=True)
        await client.start()
        client.start_display()
        try:
            original_id = client.session_id
            target = Session.create(work_dir=tmp_path)
            target.vanilla = True
            target.ensure_meta_exists()
            target.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("kept prompt")),
                    message.AssistantMessage(parts=message.text_parts_from_str("kept answer")),
                ]
            )
            await target.wait_for_flush()
            await client.components.runtime.submit_and_wait(
                op.InitAgentOperation(
                    session_id=target.id,
                    work_dir=tmp_path,
                    suppress_welcome=True,
                    defer_replay=True,
                )
            )
            actor = client.components.runtime.session_registry.get_session_actor(target.id)
            assert actor is not None
            preloaded = actor.get_agent()
            await client.wait_for_display_idle()
            seen.clear()
            await client.switch_session(target.id)
            await client.wait_for_display_idle()
            assert client.command_agent() is preloaded
            assert (
                len(
                    [
                        event
                        for event in seen
                        if isinstance(event, events.WelcomeEvent) and event.session_id == target.id
                    ]
                )
                == 1
            )
            replay = [
                event
                for event in seen
                if isinstance(event, events.ReplayHistoryEvent) and event.session_id == target.id
            ]
            assert len(replay) == 1
            assert "kept answer" in str(replay[0]) and "kept prompt" in str(replay[0])
            assert client.components.runtime.current_session_id() == target.id
            assert not SessionLease.is_active(original_id) and SessionLease.is_active(target.id)
            assert fake_llm.call_count == 0
        finally:
            await client.close()

    asyncio.run(run())
