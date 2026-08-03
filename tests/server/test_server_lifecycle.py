from __future__ import annotations

import os
from pathlib import Path

import pytest

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
    assert payload["sessions"] == {"loaded": 0, "running": 0, "waiting_input": 0}


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
