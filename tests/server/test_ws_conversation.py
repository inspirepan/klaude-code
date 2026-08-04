# pyright: reportPrivateUsage=false
from __future__ import annotations

import threading
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.store import JsonlSessionWriter

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, extract_text, send_user_message, usage


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

        send_user_message(websocket, session_id, "hi")
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


def test_history_prefers_in_memory_session_while_writer_is_still_flushing(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_started = threading.Event()
    release_write = threading.Event()
    original_write_batch_sync = JsonlSessionWriter._write_batch_sync

    def _blocked_write_batch_sync(self: JsonlSessionWriter, batch: Any) -> None:
        write_started.set()
        assert release_write.wait(timeout=5.0)
        original_write_batch_sync(self, batch)

    monkeypatch.setattr(JsonlSessionWriter, "_write_batch_sync", _blocked_write_batch_sync)

    app_env.fake_llm.enqueue(
        message.AssistantMessage(
            parts=[message.TextPart(text="fresh reply")],
            stop_reason="stop",
            usage=usage(input_tokens=12, output_tokens=4),
        )
    )

    session_id = app_env.create_session()
    try:
        with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
            consume_ws_handshake(websocket)
            send_user_message(websocket, session_id, "hello")
            _ = collect_events_until(websocket, "operation.finished")

            assert write_started.wait(timeout=1.0)

            history_response = app_env.client.get(f"/api/sessions/{session_id}/history")
            assert history_response.status_code == 200
            history_types = [event["event_type"] for event in history_response.json()["events"]]
            assert "user.message" in history_types
            assert "assistant.text.delta" in history_types
    finally:
        release_write.set()
