# pyright: reportPrivateUsage=false
from __future__ import annotations

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, extract_text, send_user_message, usage


def test_send_message_and_receive_events(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="Hello "),
        message.AssistantTextDelta(content="world!"),
        message.AssistantMessage(
            parts=[message.TextPart(text="Hello world!")],
            stop_reason="stop",
            usage=usage(input_tokens=12, output_tokens=4),
        ),
    )

    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)

        send_user_message(websocket, session_id, "hi")
        events = collect_events_until(websocket, "operation.finished")

    event_types = [event["event_type"] for event in events]
    assert "user.message" in event_types
    assert "assistant.text.start" in event_types
    assert "assistant.text.delta" in event_types
    assert "assistant.text.end" in event_types
    assert "operation.finished" in event_types
    assert extract_text(events) == "Hello world!"


def test_usage_snapshot_on_reconnect(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="first"),
        message.AssistantMessage(
            parts=[message.TextPart(text="first")],
            stop_reason="stop",
            usage=usage(input_tokens=20, output_tokens=8),
        ),
    )

    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        first_snapshot = consume_ws_handshake(websocket)
        assert first_snapshot["event"]["usage"]["input_tokens"] == 0

        send_user_message(websocket, session_id, "hello")
        _ = collect_events_until(websocket, "operation.finished")

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        reconnect_snapshot = consume_ws_handshake(websocket)
        assert reconnect_snapshot["event"]["usage"]["input_tokens"] > 0
        assert reconnect_snapshot["event"]["usage"]["output_tokens"] > 0


def test_multiple_ws_receive_same_events(app_env: AppEnv) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="broadcast"),
        message.AssistantMessage(
            parts=[message.TextPart(text="broadcast")],
            stop_reason="stop",
            usage=usage(input_tokens=9, output_tokens=3),
        ),
    )

    session_id = app_env.create_session()
    with (
        app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws1,
        app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws2,
    ):
        consume_ws_handshake(ws1)
        consume_ws_handshake(ws2)

        send_user_message(ws1, session_id, "go")
        events1 = collect_events_until(ws1, "operation.finished")
        events2 = collect_events_until(ws2, "operation.finished")

    assert extract_text(events1) == "broadcast"
    assert extract_text(events2) == "broadcast"


def test_op_after_actor_reclaim_rehydrates_agent(app_env: AppEnv) -> None:
    """Typing hours later must not fail with "work_dir is required".

    The idle reaper can drop the in-memory agent while the TUI stays
    attached; the next op frame rehydrates it silently (no welcome banner
    in the middle of the transcript).
    """
    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)

        # Simulate the idle reaper: drop the actor from under the client.
        assert app_env.client.portal is not None
        assert app_env.client.portal.call(app_env.runtime.close_session, session_id)
        assert not app_env.runtime.session_registry.has_session_actor(session_id)

        app_env.fake_llm.enqueue(
            message.AssistantTextDelta(content="rehydrated reply"),
            message.AssistantMessage(
                parts=[message.TextPart(text="rehydrated reply")],
                stop_reason="stop",
                usage=usage(input_tokens=8, output_tokens=3),
            ),
        )
        send_user_message(websocket, session_id, "after reclaim")
        # The first operation.finished belongs to the silent rehydration
        # (InitAgentOperation); wait for the actual turn to finish.
        events = collect_events_until(websocket, "task.finish")

    event_types = [event["event_type"] for event in events]
    assert "error" not in event_types
    assert "welcome" not in event_types
    assert extract_text(events) == "rehydrated reply"
