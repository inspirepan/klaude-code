from __future__ import annotations

import json
from typing import Any, cast

import pytest

from klaude_code.config import load_config
from klaude_code.protocol import op

from .conftest import AppEnv, consume_ws_handshake, op_frame, wait_for_event


def _meta_path_for_session(app_env: AppEnv, session_id: str):
    paths = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(paths) == 1
    return paths[0]


def test_change_model_via_ws(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    cast(Any, load_config).cache_clear()

    config = load_config()
    model_names = [entry.selector for entry in config.iter_model_entries(only_available=True, include_disabled=False)]

    session_id = app_env.create_session()

    model_name = next((name.strip() for name in model_names if name.strip()), "sonnet@anthropic")

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        websocket.send_json(
            op_frame(op.ChangeModelOperation(session_id=session_id, model_name=model_name, save_as_default=False))
        )
        event = wait_for_event(websocket, "model.changed")

    assert event["event_type"] == "model.changed"
    assert event["event"]["model_id"]


def test_configure_resume_model_rehydrates_from_server_metadata(app_env: AppEnv) -> None:
    session_id = app_env.create_session()
    assert app_env.runtime.session_registry.get_session_actor(session_id) is not None

    response = app_env.client.put(
        f"/api/sessions/{session_id}/model/config",
        json={"model_name": "resume-model"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert app_env.runtime.session_registry.get_session_actor(session_id) is None
    meta = json.loads(_meta_path_for_session(app_env, session_id).read_text(encoding="utf-8"))
    assert meta["model_config_name"] == "resume-model"
