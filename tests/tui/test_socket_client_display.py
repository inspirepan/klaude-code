"""Client-side display behaviors: echo swallows, welcome-context splice, busy states."""

from __future__ import annotations

import asyncio
import time

import pytest

from klaude_code.protocol import events, llm_param
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


def test_waiting_user_input_counts_as_busy() -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    client._apply_session_info({"state": "waiting_user_input"})
    assert client.is_running() is True

    client._apply_session_info({"state": "running"})
    assert client.is_running() is True

    client._apply_session_info({"state": "idle"})
    assert client.is_running() is False
