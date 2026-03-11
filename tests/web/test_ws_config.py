from __future__ import annotations

from typing import Any, cast

import pytest

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


def test_request_model_via_ws(app_env: AppEnv) -> None:
    models_response = app_env.client.get("/api/config/models")
    assert models_response.status_code == 200
    models = models_response.json().get("models", [])
    assert isinstance(models, list)
    assert models
    first_model = models[0]
    assert isinstance(first_model, dict)
    preferred = str(first_model.get("name", "")).strip()
    assert preferred

    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json({"type": "model_request", "preferred": preferred, "save_as_default": False})

        finished = None
        for _ in range(200):
            frame = websocket.receive_json()
            if frame.get("type") == "error":
                pytest.fail(f"unexpected ws error frame: {frame}")
            if frame.get("event_type") != "operation.finished":
                continue
            payload_obj = frame.get("event")
            payload = cast(dict[str, Any], payload_obj) if isinstance(payload_obj, dict) else None
            if payload is not None and payload.get("operation_type") == "request_model":
                finished = frame
                break

    assert finished is not None
    assert finished["event"]["status"] == "completed"


def test_get_models(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/config/models")
    assert response.status_code == 200
    payload = response.json()
    assert "models" in payload
    assert isinstance(payload["models"], list)


def test_request_model_operation_via_http(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    response = app_env.client.post(
        f"/api/sessions/{session_id}/model/request",
        json={"preferred": "fake", "save_as_default": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("operation_id"), str)
