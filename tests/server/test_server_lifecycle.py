from __future__ import annotations

import os
from pathlib import Path

import pytest

from klaude_code.config.config import Config, ModelConfig, ProviderConfig
from klaude_code.protocol import llm_param
from klaude_code.protocol.env_sync import encode_env_header
from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.server import routes
from klaude_code.server.server import ServerAlreadyRunningError, _SingletonLock  # pyright: ignore[reportPrivateUsage]

from .conftest import AppEnv


def test_status_endpoint_reports_server_info(app_env: AppEnv) -> None:
    response = app_env.client.get("/api/server/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["pid"] == os.getpid()
    assert isinstance(payload["version"], str) and payload["version"]
    assert payload["socket_path"].endswith("server.sock")
    assert payload["uptime_seconds"] >= 0
    assert isinstance(payload["code_fingerprint"], str) and payload["code_fingerprint"]
    assert payload["protocol_version"] == PROTOCOL_VERSION
    assert payload["sessions"] == {"loaded": 0, "running": 0, "waiting_input": 0, "queued": 0}


def test_stop_endpoint_triggers_shutdown(app_env: AppEnv) -> None:
    response = app_env.client.post("/api/server/stop")
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert app_env.exit_calls == [True]
    assert app_env.lifecycle.reload_requested is False


def test_reload_endpoint_with_idle_server(app_env: AppEnv) -> None:
    response = app_env.client.post("/api/server/reload", json={"force": False})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert app_env.exit_calls == [True]
    assert app_env.lifecycle.reload_requested is True


def test_reload_endpoint_refuses_active_sessions(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_active = [{"session_id": "abc123", "state": "running"}]
    monkeypatch.setattr(routes.server, "list_active_sessions", lambda _runtime: fake_active)

    response = app_env.client.post("/api/server/reload", json={"force": False})
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["sessions"] == fake_active
    assert app_env.exit_calls == []
    assert app_env.lifecycle.reload_requested is False

    forced = app_env.client.post("/api/server/reload", json={"force": True})
    assert forced.status_code == 200
    assert app_env.exit_calls == [True]
    assert app_env.lifecycle.reload_requested is True


def test_env_sync_middleware_merges_client_env(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KLAUDE_SYNC_TEST_KEY", "")
    payload = encode_env_header({"KLAUDE_SYNC_TEST_KEY": "from-client"})

    response = app_env.client.get("/api/server/status", headers={"X-Klaude-Env": payload})

    assert response.status_code == 200
    assert os.environ.get("KLAUDE_SYNC_TEST_KEY") == "from-client"


def test_env_sync_middleware_ignores_malformed_header(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KLAUDE_SYNC_TEST_KEY", "")
    response = app_env.client.get("/api/server/status", headers={"X-Klaude-Env": "!!!not-base64-json!!!"})

    assert response.status_code == 200
    assert os.environ.get("KLAUDE_SYNC_TEST_KEY") in (None, "")


def _env_sync_test_config() -> Config:
    """Deterministic config: one provider whose key comes from ${KLAUDE_SYNC_TEST_KEY}."""
    return Config(
        provider_list=[
            ProviderConfig(
                provider_name="env-provider",
                protocol=llm_param.LLMClientProtocol.OPENAI,
                api_key="${KLAUDE_SYNC_TEST_KEY}",
                model_list=[ModelConfig(model_name="env-model", model_id="env/test-model")],
            )
        ]
    )


def test_create_session_accepts_model_after_env_sync(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    """The client's env header reaches the availability check (user's `-m ox` flow)."""
    monkeypatch.setenv("KLAUDE_SYNC_TEST_KEY", "")
    monkeypatch.setattr("klaude_code.config.load_config", _env_sync_test_config)
    payload_body = {"work_dir": str(app_env.work_dir), "model": "env-model"}

    baseline = app_env.client.post("/api/sessions", json=payload_body)
    assert baseline.status_code == 400
    assert "is unavailable" in baseline.json()["detail"]

    env_header = encode_env_header({"KLAUDE_SYNC_TEST_KEY": "sk-fake-for-test"})
    with_env = app_env.client.post("/api/sessions", json=payload_body, headers={"X-Klaude-Env": env_header})
    assert with_env.status_code == 200
    assert "session_id" in with_env.json()


def test_debug_endpoint_enables_file_logging(app_env: AppEnv, monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.log import DebugType, is_debug_enabled, log_debug, logger, set_debug_logging

    log_dir = app_env.home_dir / ".klaude" / "logs"
    monkeypatch.setattr("klaude_code.log.DEFAULT_DEBUG_LOG_DIR", log_dir)
    monkeypatch.setattr("klaude_code.log.DEFAULT_DEBUG_LOG_FILE", log_dir / "debug.log")

    try:
        response = app_env.client.post("/api/server/debug", json={"enabled": True})
        assert response.status_code == 200
        payload = response.json()
        assert payload["ok"] is True
        assert payload["enabled"] is True
        log_path = Path(payload["log_file"])
        assert log_path.is_file()
        assert log_path.is_relative_to(log_dir)
        assert is_debug_enabled()

        log_debug("viewer-probe", debug_type=DebugType.LLM_PAYLOAD)
        for handler in logger.handlers:
            handler.flush()
        text = log_path.read_text(encoding="utf-8")
        assert "LLM_PAYLOAD" in text
        assert "viewer-probe" in text
    finally:
        set_debug_logging(False)


def test_singleton_lock_rejects_second_holder(tmp_path: Path) -> None:
    lock_path = tmp_path / "run" / "server.lock"
    first = _SingletonLock(lock_path)
    second = _SingletonLock(lock_path)

    first.acquire()
    try:
        assert lock_path.read_text(encoding="utf-8").strip() == str(os.getpid())
        with pytest.raises(ServerAlreadyRunningError, match="already running"):
            second.acquire()
    finally:
        first.release()

    # After release the lock can be re-acquired.
    second.acquire()
    second.release()
