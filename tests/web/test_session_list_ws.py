from __future__ import annotations

from typing import Any, cast

from .conftest import AppEnv


def test_session_list_websocket_receives_upsert(app_env: AppEnv) -> None:
    with app_env.client.websocket_connect("/api/sessions/ws") as websocket:
        session_id = app_env.create_session()
        event = websocket.receive_json()
        assert isinstance(event, dict)
        payload = cast(dict[str, Any], event)
        assert payload["type"] == "session.upsert"
        assert payload["session_id"] == session_id
        assert isinstance(payload["session"], dict)
        assert payload["session"]["id"] == session_id
