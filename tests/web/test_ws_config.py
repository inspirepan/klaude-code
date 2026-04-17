from __future__ import annotations

from typing import Any, cast

import pytest

from klaude_code.config import load_config

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


def test_change_model_via_ws(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    load_config.cache_clear()

    models_response = app_env.client.get("/api/config/models")
    assert models_response.status_code == 200
    response_obj = models_response.json()
    response_payload = cast(dict[str, object], response_obj) if isinstance(response_obj, dict) else {}
    models_obj = response_payload.get("models", [])
    assert isinstance(models_obj, list)
    models = cast(list[object], models_obj)

    session_id = app_env.create_session()

    sessions_response = app_env.client.get("/api/sessions")
    assert sessions_response.status_code == 200
    sessions_payload = sessions_response.json()
    groups = cast(list[dict[str, Any]], sessions_payload.get("groups", []))
    session_summary = next(
        session
        for group in groups
        for session in cast(list[dict[str, Any]], group.get("sessions", []))
        if session.get("id") == session_id
    )
    current_model_name = str(session_summary.get("model_name") or "")

    model_name = next(
        (
            str(cast(dict[str, object], model).get("name", "")).strip()
            for model in models
            if isinstance(model, dict)
            and str(cast(dict[str, object], model).get("name", "")).strip() != current_model_name
        ),
        "sonnet@anthropic",
    )

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json({"type": "model", "model_name": model_name, "save_as_default": False})
        event = wait_for_event(websocket, "model.changed")

    assert event["event_type"] == "model.changed"
    assert event["event"]["model_id"]


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
        json={"initial_search_text": "fake", "save_as_default": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("operation_id"), str)
