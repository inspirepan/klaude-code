"""Client-side display behaviors: echo swallows, welcome-context splice, busy states."""

from __future__ import annotations

import asyncio
import time

import pytest

from klaude_code.protocol import events, llm_param, user_interaction
from klaude_code.protocol.models.session_status import SessionStatus
from klaude_code.tui.client.base import ClientConnectionError
from klaude_code.tui.client.socket_client import _ECHO_SWALLOW_TTL_SECONDS, SocketRuntimeClient, _local_envelope


async def _ignore_envelope(_envelope: events.EventEnvelope) -> None:
    return


def _welcome_event(session_id: str) -> events.WelcomeEvent:
    return events.WelcomeEvent(
        session_id=session_id,
        work_dir="/tmp",
        llm_config=llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.OPENAI),
    )


def test_welcome_context_spliced_before_history_replay() -> None:
    context_event = events.WelcomeContextEvent(
        session_id="session-id",
        work_dir="/tmp",
        loaded_skills={"user": ["image-gen"]},
    )

    async def provide_context() -> events.WelcomeContextEvent:
        return context_event

    client = SocketRuntimeClient(
        "session-id",
        on_envelope=_ignore_envelope,
        welcome_context_provider=provide_context,
    )
    client._welcome_context_pending = True

    async def scenario() -> list[events.Event]:
        await client._handle_envelope(_local_envelope(_welcome_event("session-id")))
        await client._handle_frame(
            {
                "type": "replay_history",
                "session_id": "session-id",
                "updated_at": 1.0,
                "events": [],
            }
        )
        await client._handle_frame({"type": "replay_complete", "session_id": "session-id"})
        received: list[events.Event] = []
        while not client._display_queue.empty():
            received.append(client._display_queue.get_nowait().event)
        return received

    received = asyncio.run(scenario())
    assert [type(e) for e in received] == [
        events.WelcomeEvent,
        events.WelcomeContextEvent,
        events.ReplayHistoryEvent,
    ]
    assert received[1] is context_event


def test_welcome_context_not_injected_after_replay_complete() -> None:
    async def provide_context() -> events.WelcomeContextEvent:
        raise AssertionError("provider must not run for post-replay welcomes")

    client = SocketRuntimeClient(
        "session-id",
        on_envelope=_ignore_envelope,
        welcome_context_provider=provide_context,
    )
    client._welcome_context_pending = True
    client._replay_complete.set()

    async def scenario() -> list[events.Event]:
        # A model-switch welcome arriving mid-session must render alone.
        await client._handle_envelope(_local_envelope(_welcome_event("session-id")))
        received: list[events.Event] = []
        while not client._display_queue.empty():
            received.append(client._display_queue.get_nowait().event)
        return received

    received = asyncio.run(scenario())
    assert [type(e) for e in received] == [events.WelcomeEvent]


def test_echo_swallow_matches_once_and_expires() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    now = time.monotonic()
    client._pending_echo_swallows.append(("hello", now))
    assert client._swallow_pending_echo("hello") is True
    # Swallowed once: the same text later is a genuine new message.
    assert client._swallow_pending_echo("hello") is False

    # An expired entry is pruned instead of eating a fresh message.
    client._pending_echo_swallows.append(("stale", now - _ECHO_SWALLOW_TTL_SECONDS - 1))
    assert client._swallow_pending_echo("stale") is False
    assert not client._pending_echo_swallows


def test_failed_emit_does_not_arm_echo_swallow() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    event = events.UserMessageEvent(session_id="session-id", content="hello")

    async def scenario() -> None:
        with pytest.raises(ClientConnectionError):
            await client.emit_user_message(event)

    asyncio.run(scenario())
    # The send never reached the wire: no canonical echo will come back, so
    # no swallow may lie in wait for the next same-text message.
    assert not client._pending_echo_swallows


def test_fatal_turn_end_waits_for_authoritative_status() -> None:
    """Operation completion clears identity, not the product status."""
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    start = _local_envelope(events.TaskStartEvent(session_id="session-id")).model_copy(update={"operation_id": "op-1"})
    finish = _local_envelope(
        events.OperationFinishedEvent(
            session_id="session-id",
            operation_id="op-1",
            operation_type="run_agent",
            status="completed",
        )
    )

    async def scenario() -> None:
        client._replay_complete.set()
        client._apply_session_info({"status": {"category": "working", "execution": "running"}})
        await client._handle_envelope(start)
        assert client.is_running() is True
        await client._handle_envelope(
            _local_envelope(events.ErrorEvent(session_id="session-id", error_message="Step failed", can_retry=False))
        )
        assert client.is_running() is True
        await client._handle_envelope(finish)
        assert client.is_running() is True
        await client._handle_envelope(
            _local_envelope(
                events.SessionStatusEvent(session_id="session-id", status=SessionStatus(category="needs_you"))
            )
        )
        assert client.is_running() is False

    asyncio.run(scenario())


def test_stale_operation_finished_does_not_release_new_turn() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    start = _local_envelope(events.TaskStartEvent(session_id="session-id")).model_copy(update={"operation_id": "op-2"})
    stale_finish = _local_envelope(
        events.OperationFinishedEvent(
            session_id="session-id",
            operation_id="op-1",
            operation_type="run_agent",
            status="completed",
        )
    )

    async def scenario() -> None:
        client._replay_complete.set()
        client._apply_session_info({"status": {"category": "working", "execution": "running"}})
        await client._handle_envelope(start)
        await client._handle_envelope(stale_finish)
        assert client.is_running() is True

    asyncio.run(scenario())


def test_attention_and_execution_are_independent() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    client._apply_session_info({"status": {"category": "needs_you", "execution": "running"}})
    assert client.is_running() is True

    client._apply_session_info({"status": {"category": "working", "execution": "queued"}})
    assert client.is_running() is True

    client._apply_session_info({"status": {"category": "working", "execution": "waiting_agents"}})
    assert client.is_running() is False


def test_attach_status_ignores_taped_pause_and_tracks_live_parent_status() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    current = SessionStatus(category="working", execution="waiting_agents")
    paused = SessionStatus.model_validate(
        {
            "category": "needs_you",
            "control": {"paused": True},
            "attention": [{"kind": "paused", "code": "user_interrupt", "source_session_id": "session-id"}],
        }
    )

    async def scenario() -> None:
        await client._handle_frame({"type": "session_info", "status": current.model_dump()})
        initial = client._display_queue.get_nowait().event
        assert isinstance(initial, events.SessionStatusEvent)
        assert initial.status == current
        await client._handle_envelope(
            _local_envelope(events.SessionStatusEvent(session_id="session-id", status=paused))
        )
        assert client.session_info().status == current
        assert client._display_queue.empty()
        await client._handle_frame({"type": "replay_complete"})
        needs_input = paused.model_copy(update={"execution": "running"})
        await client._handle_envelope(
            _local_envelope(events.SessionStatusEvent(session_id="session-id", status=needs_input))
        )
        assert client.session_info().status == needs_input
        assert client.session_info().state == "needs_you"
        assert client.is_running()
        await client._handle_envelope(_local_envelope(events.InterruptEvent(session_id="session-id")))
        assert client.is_running()

    asyncio.run(scenario())


def test_session_info_mirrors_the_active_model() -> None:
    """The prompt bar reads the model that runs, not only the stored selector."""
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    client._apply_session_info(
        {
            "status": {},
            "model_config_name": "removed-model",
            "active_model_name": "sonnet",
            "provider_name": "anthropic",
        }
    )

    info = client.session_info()
    assert info.model_config_name == "removed-model"
    assert info.active_model_name == "sonnet"


def test_session_info_without_an_active_model_stays_none() -> None:
    """An older server sends no active model; the snapshot must not invent one."""
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    client._apply_session_info({"status": {}, "model_config_name": "sonnet"})

    assert client.session_info().active_model_name is None


def test_chunked_history_replay_reaches_the_display_as_one_replay() -> None:
    """Each replay is a rebuild that resets display state; chunks must not be split
    into several, or a child turn crossing a chunk boundary loses its block."""
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    def chunk(text: str) -> dict[str, object]:
        event = events.UserMessageEvent(session_id="session-id", content=text)
        return {
            "type": "replay_history",
            "session_id": "session-id",
            "updated_at": 1.0,
            "events": [{"event_type": events.event_type_name(event), "event": event.model_dump(mode="json")}],
        }

    async def scenario() -> list[events.Event]:
        await client._handle_frame(chunk("first"))
        await client._handle_frame(chunk("second"))
        assert client._display_queue.empty()
        await client._handle_frame({"type": "replay_complete", "session_id": "session-id"})
        received: list[events.Event] = []
        while not client._display_queue.empty():
            received.append(client._display_queue.get_nowait().event)
        return received

    received = asyncio.run(scenario())
    assert len(received) == 1 and isinstance(received[0], events.ReplayHistoryEvent)
    assert [event.content for event in received[0].events if isinstance(event, events.UserMessageEvent)] == [
        "first",
        "second",
    ]


@pytest.mark.parametrize("child", [False, True])
@pytest.mark.parametrize("cancelled", [False, True])
def test_interaction_snapshot_dedup_and_remote_close(child: bool, cancelled: bool) -> None:
    async def scenario() -> None:
        client = SocketRuntimeClient("root", on_envelope=_ignore_envelope)
        session_id = "child" if child else "root"
        if child:
            client._child_session_ids.add(session_id)
        request = events.UserInteractionRequestEvent(
            session_id=session_id,
            request_id="request",
            source="tool",
            payload=user_interaction.AskUserQuestionRequestPayload(questions=[]),
        )
        await client._handle_envelope(_local_envelope(request))
        closed = client.interaction_closed_event(request)
        await client._handle_envelope(_local_envelope(request))
        assert client.interaction_requests().qsize() == 1
        assert not closed.is_set()
        terminal = (
            events.UserInteractionCancelledEvent(session_id=session_id, request_id="request", reason="interrupt")
            if cancelled
            else events.UserInteractionResolvedEvent(session_id=session_id, request_id="request", status="submitted")
        )
        await client._handle_envelope(_local_envelope(terminal))
        assert closed.is_set()
        queued = client.interaction_requests().get_nowait()
        assert client.interaction_closed_event(queued).is_set()
        await client._handle_envelope(_local_envelope(request))
        assert client.interaction_requests().empty()

    asyncio.run(scenario())


def test_interaction_reconnect_closes_old_modal_and_accepts_pending_snapshot() -> None:
    async def scenario() -> None:
        client = SocketRuntimeClient("root", on_envelope=_ignore_envelope)
        request = events.UserInteractionRequestEvent(
            session_id="root",
            request_id="request",
            source="tool",
            payload=user_interaction.AskUserQuestionRequestPayload(questions=[]),
        )
        await client._handle_envelope(_local_envelope(request))
        old_closed = client.interaction_closed_event(request)
        client._reset_pending_interactions()
        assert old_closed.is_set()
        assert client.interaction_requests().empty()
        await client._handle_envelope(_local_envelope(request))
        assert not client.interaction_closed_event(request).is_set()
        assert client.interaction_requests().qsize() == 1

    asyncio.run(scenario())
