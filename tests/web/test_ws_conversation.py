from __future__ import annotations

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, extract_text, usage


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
        snapshot = websocket.receive_json()
        assert snapshot["event_type"] == "usage.snapshot"

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
        first_snapshot = websocket.receive_json()
        assert first_snapshot["event_type"] == "usage.snapshot"
        assert first_snapshot["event"]["usage"]["input_tokens"] == 0

        websocket.send_json({"type": "message", "text": "hello"})
        _ = collect_events_until(websocket, "operation.finished")

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        reconnect_snapshot = websocket.receive_json()
        assert reconnect_snapshot["event_type"] == "usage.snapshot"
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
        assert ws1.receive_json()["event_type"] == "usage.snapshot"
        assert ws2.receive_json()["event_type"] == "usage.snapshot"

        ws1.send_json({"type": "message", "text": "go"})
        events1 = collect_events_until(ws1, "operation.finished")
        events2 = collect_events_until(ws2, "operation.finished")

    assert extract_text(events1) == "broadcast"
    assert extract_text(events2) == "broadcast"
