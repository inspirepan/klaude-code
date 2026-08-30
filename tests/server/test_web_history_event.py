"""`history.appended`: the store's "disk grew" ping for REST-reading clients.

The writer flushes in a worker thread, so the event only reaches subscribers
if the bridge hands it back to the server loop (`server/history_bridge.py`).
It is a pointer, not content: it must be forwarded live but never replayed
from the attach tape.
"""

from __future__ import annotations

import time
from typing import Any

from klaude_code.protocol import message

from .conftest import AppEnv, collect_events_until, consume_ws_handshake, send_user_message, usage


def _reply(app_env: AppEnv, text: str) -> None:
    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content=text),
        message.AssistantMessage(parts=[message.TextPart(text=text)], stop_reason="stop", usage=usage()),
    )


def test_history_appended_reaches_a_live_ws_client(app_env: AppEnv) -> None:
    _reply(app_env, "written")
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "persist this")
        events = collect_events_until(websocket, "history.appended")

    appended = [event for event in events if event["event_type"] == "history.appended"]
    assert appended, "no history.appended frame"
    assert appended[0]["session_id"] == session_id
    assert appended[0]["event"]["line_count"] > 0
    # The count is the ledger's exclusive upper bound, so it matches the REST view.
    payload = app_env.client.get(f"/api/web/sessions/{session_id}/history").json()
    assert payload["line_count"] >= appended[0]["event"]["line_count"]


def test_history_appended_is_not_replayed_on_attach(app_env: AppEnv) -> None:
    _reply(app_env, "done")
    session_id = app_env.create_session()

    response = app_env.client.post(f"/api/headless/sessions/{session_id}/send", json={"text": "hello"})
    assert response.status_code == 200
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if app_env.client.get(f"/api/headless/sessions/{session_id}/brief").json()["state"] == "completed":
            break
        time.sleep(0.05)

    replayed: list[dict[str, Any]] = []
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws?replay=1") as websocket:
        assert websocket.receive_json()["type"] == "connection_info"
        assert websocket.receive_json()["type"] == "session_info"
        assert websocket.receive_json()["event_type"] == "usage.snapshot"
        while True:
            frame = websocket.receive_json()
            items = frame if isinstance(frame, list) else [frame]
            if any(item.get("type") == "replay_complete" for item in items):
                replayed.extend(item for item in items if item.get("type") != "replay_complete")
                break
            replayed.extend(items)

    assert replayed, "attach replayed nothing"
    assert all(item.get("event_type") != "history.appended" for item in replayed)
