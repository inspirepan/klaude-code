from __future__ import annotations

from typing import Any, cast

import pytest

from klaude_code.config import load_config
from klaude_code.protocol import op

from .conftest import AppEnv, consume_ws_handshake, op_frame, wait_for_event


def test_change_model_via_ws(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cast(Any, load_config).cache_clear()

    config = load_config()
    model_names = [entry.selector for entry in config.iter_model_entries(only_available=True, include_disabled=False)]

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
        (name.strip() for name in model_names if name.strip() != current_model_name),
        "sonnet@anthropic",
    )

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json(
            op_frame(op.ChangeModelOperation(session_id=session_id, model_name=model_name, save_as_default=False))
        )
        event = wait_for_event(websocket, "model.changed")

    assert event["event_type"] == "model.changed"
    assert event["event"]["model_id"]


def test_request_model_operation_via_http(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    response = app_env.client.post(
        f"/api/sessions/{session_id}/model/request",
        json={"initial_search_text": "fake", "save_as_default": False},
    )
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload.get("operation_id"), str)
