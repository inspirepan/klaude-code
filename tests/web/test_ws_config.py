from __future__ import annotations

from .conftest import AppEnv, consume_ws_handshake, wait_for_event


def test_change_thinking_via_ws(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json(
            {
                "type": "thinking",
                "thinking": {
                    "type": "enabled",
                    "budget_tokens": 2048,
                },
            }
        )
        event = wait_for_event(websocket, "thinking.changed")

    assert event["event_type"] == "thinking.changed"
    assert "current" in event["event"]


def test_get_models(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/config/models")
    assert response.status_code == 200
    payload = response.json()
    assert "models" in payload
    assert isinstance(payload["models"], list)
