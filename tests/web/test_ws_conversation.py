from __future__ import annotations

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, extract_text, usage


def test_send_message_receive_events_and_history(app_env: AppEnv) -> None:
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

        websocket.send_json({"type": "message", "text": "hi"})
        events = collect_events_until(websocket, "operation.finished")

    event_types = [event["event_type"] for event in events]
    assert "user.message" in event_types
    assert "assistant.text.start" in event_types
    assert "assistant.text.delta" in event_types
    assert "assistant.text.end" in event_types
    assert "operation.finished" in event_types
    assert extract_text(events) == "Hello world!"

    history_response = app_env.client.get(f"/api/sessions/{session_id}/history")
    assert history_response.status_code == 200
    history_types = [event["event_type"] for event in history_response.json()["events"]]
    assert "user.message" in history_types
    assert "task.finish" in history_types


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

        websocket.send_json({"type": "message", "text": "hello"})
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

        ws1.send_json({"type": "message", "text": "go"})
        events1 = collect_events_until(ws1, "operation.finished")
        events2 = collect_events_until(ws2, "operation.finished")

    assert extract_text(events1) == "broadcast"
    assert extract_text(events2) == "broadcast"


def test_second_ws_connection_cannot_send_commands(app_env: AppEnv) -> None:
    """A non-holder connection must receive session_not_held for write commands."""
    session_id = app_env.create_session()
    with (
        app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws_holder,
        app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as ws_reader,
    ):
        holder_info = ws_holder.receive_json()
        assert holder_info["type"] == "connection_info"
        assert holder_info["is_holder"] is True
        _ = ws_holder.receive_json()  # usage.snapshot

        reader_info = ws_reader.receive_json()
        assert reader_info["type"] == "connection_info"
        assert reader_info["is_holder"] is False
        _ = ws_reader.receive_json()  # usage.snapshot

        # Reader tries to send a message -- should be rejected.
        ws_reader.send_json({"type": "message", "text": "should fail"})
        error = ws_reader.receive_json()
        assert error["type"] == "error"
        assert error["code"] == "session_not_held"


def test_rest_write_requires_holder_key_when_held(app_env: AppEnv) -> None:
    """REST write endpoints enforce holder when a WS connection holds the session."""
    session_id = app_env.create_session()

    # Acquire holder via WS, then test REST access.
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?holder_key=my-secret-key") as ws:
        info = ws.receive_json()
        assert info["is_holder"] is True
        _ = ws.receive_json()  # usage.snapshot

        # No holder key header while session is held -- should be 409.
        resp = app_env.client.post(f"/api/sessions/{session_id}/message", json={"text": "hi"})
        assert resp.status_code == 409
        assert "held by another" in resp.json()["detail"]

        # Wrong holder key -- should be 409.
        resp = app_env.client.post(
            f"/api/sessions/{session_id}/interrupt",
            headers={"X-Holder-Key": "wrong-key"},
        )
        assert resp.status_code == 409

        # Correct holder key -- should succeed.
        app_env.fake_llm.enqueue(
            message.AssistantTextDelta(content="ok"),
            message.AssistantMessage(
                parts=[message.TextPart(text="ok")],
                stop_reason="stop",
                usage=usage(input_tokens=5, output_tokens=1),
            ),
        )
        resp = app_env.client.post(
            f"/api/sessions/{session_id}/message",
            json={"text": "hi"},
            headers={"X-Holder-Key": "my-secret-key"},
        )
        assert resp.status_code == 200
