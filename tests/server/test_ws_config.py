from __future__ import annotations

import json
from typing import Any, cast

import pytest

from klaude_code.config import load_config
from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.protocol import llm_param, op
from klaude_code.session.store_registry import get_store_for_path

from .conftest import AppEnv, consume_ws_handshake, op_frame, wait_for_event


def _meta_path_for_session(app_env: AppEnv, session_id: str):
    paths = list((app_env.home_dir / ".klaude" / "projects").glob(f"*/sessions/{session_id}/meta.json"))
    assert len(paths) == 1
    return paths[0]


def _model_availability_config() -> Config:
    """Deterministic config: one keyed provider plus one whose key never resolves."""
    return Config(
        provider_list=[
            ProviderConfig(
                provider_name="test-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="test-key",
                model_list=[ModelConfig(model_name="test-model", model_id="test/model")],
            ),
            ProviderConfig(
                provider_name="gated-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${KLAUDE_NO_SUCH_VAR}",
                model_list=[ModelConfig(model_name="gated-model", model_id="gated/model")],
            ),
        ]
    )


def _stored_model(app_env: AppEnv, session_id: str) -> str | None:
    meta = get_store_for_path(app_env.work_dir.resolve()).load_meta(session_id)
    assert meta is not None
    return cast("str | None", meta.get("model_config_name"))


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


def test_configure_resume_model_rehydrates_from_server_metadata(
    app_env: AppEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("klaude_code.config.load_config", _model_availability_config)
    session_id = app_env.create_session()
    assert app_env.runtime.session_registry.get_session_actor(session_id) is not None

    response = app_env.client.put(
        f"/api/sessions/{session_id}/model/config",
        json={"model_name": "test-model@test-provider"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert app_env.runtime.session_registry.get_session_actor(session_id) is None
    meta = json.loads(_meta_path_for_session(app_env, session_id).read_text(encoding="utf-8"))
    assert meta["model_config_name"] == "test-model@test-provider"


def test_configure_session_model_rejects_unavailable_model(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.config.load_config", _model_availability_config)
    session_id = app_env.create_session()
    previous_model = "test-model@test-provider"
    assert get_store_for_path(app_env.work_dir.resolve()).update_meta(session_id, {"model_config_name": previous_model})
    assert _stored_model(app_env, session_id) == previous_model

    # First selector names no configured model, second one sits on a provider
    # whose API key cannot resolve.
    for model_name in ("missing-model", "gated-model@gated-provider"):
        response = app_env.client.put(
            f"/api/sessions/{session_id}/model/config",
            json={"model_name": model_name},
        )
        assert response.status_code == 400
        assert "is unavailable" in cast("dict[str, str]", response.json())["detail"]

    assert _stored_model(app_env, session_id) == previous_model


def test_configure_session_model_persists_available_model(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("klaude_code.config.load_config", _model_availability_config)
    session_id = app_env.create_session()
    assert _stored_model(app_env, session_id) is None

    # Unqualified selector: the CLI resume path echoes the session's own model.
    response = app_env.client.put(
        f"/api/sessions/{session_id}/model/config",
        json={"model_name": "test-model"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert _stored_model(app_env, session_id) == "test-model"
