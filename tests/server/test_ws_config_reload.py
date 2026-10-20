"""Tests for broadcasting a config reload to every connected client."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest
import yaml

import klaude_code.config.config as _config_module
from klaude_code.app.runtime import _start_config_watcher
from klaude_code.config import ConfigReload, ConfigWatcher, config_revision, load_config
from klaude_code.protocol import events
from klaude_code.server.routes.server import server_config_reload
from klaude_code.server.routes.ws import _forwarded_to_session

from .conftest import AppEnv, consume_ws_handshake, wait_for_event


def _write_config(path: Path, main_model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"main_model": main_model}), encoding="utf-8")


def _use_config_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the loader at a scratch config file and seed it."""
    config_path = tmp_path / "klaude-config.yaml"
    _write_config(config_path, "first-model")
    monkeypatch.setattr(_config_module, "config_path", config_path)
    load_config.cache_clear()
    return config_path


def _start_watcher_on_socket_loop(websocket: Any, app_env: AppEnv) -> ConfigWatcher:
    """Run the server's config watcher on the loop that serves this socket.

    ``TestClient`` runs each operation on its own portal loop and the event bus
    delivers within one loop, so a watcher started anywhere else would publish
    into a loop this socket never sees.
    """
    return cast(ConfigWatcher, websocket.portal.call(_start_config_watcher, app_env.event_bus))


class TestForwardedToSession:
    """`_forwarded_to_session` is the socket's ownership filter."""

    def test_own_session_is_forwarded(self) -> None:
        event = events.NoticeEvent(session_id="s1", content="hi")

        decision = _forwarded_to_session(event, "s1", set())

        assert decision.forward is True
        assert decision.child_to_track is None

    def test_other_session_is_dropped(self) -> None:
        event = events.NoticeEvent(session_id="other", content="hi")

        assert _forwarded_to_session(event, "s1", set()).forward is False

    def test_config_reload_is_forwarded_to_every_session(self) -> None:
        """The config revision belongs to the server, not to one session."""
        event = events.ConfigReloadedEvent(session_id="", revision=3, summary="main model: a -> b")

        assert _forwarded_to_session(event, "s1", set()).forward is True
        assert _forwarded_to_session(event, "another-session", set()).forward is True

    def test_tracked_child_is_forwarded(self) -> None:
        event = events.NoticeEvent(session_id="child", content="hi")

        assert _forwarded_to_session(event, "s1", {"child"}).forward is True

    def test_new_child_is_reported_for_tracking(self) -> None:
        event = events.TaskStartEvent(session_id="child", parent_session_id="s1")

        decision = _forwarded_to_session(event, "s1", set())

        assert decision.forward is True
        assert decision.child_to_track == "child"

    def test_unrelated_task_start_is_dropped(self) -> None:
        event = events.TaskStartEvent(session_id="child", parent_session_id="other")

        assert _forwarded_to_session(event, "s1", set()).forward is False


def test_connection_info_carries_the_config_revision(app_env: AppEnv) -> None:
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        connection_info = websocket.receive_json()

    assert connection_info["type"] == "connection_info"
    assert connection_info["config_revision"] >= 1


def test_reload_endpoint_reports_the_new_revision(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _use_config_file(monkeypatch, tmp_path)
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        connection_info = websocket.receive_json()
        _write_config(config_path, "second-model")

        body = websocket.portal.call(server_config_reload)

    assert body["ok"] is True
    assert body["revision"] > connection_info["config_revision"]
    assert body["revision"] == config_revision()


def test_reload_endpoint_rejects_an_invalid_config(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    config_path = _use_config_file(monkeypatch, tmp_path)
    config_path.write_text("main_model: [unclosed", encoding="utf-8")

    session_id = app_env.create_session()
    with (
        app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket,
        pytest.raises(HTTPException) as exc_info,
    ):
        websocket.portal.call(server_config_reload)

    assert exc_info.value.status_code == 400


def test_watcher_broadcasts_an_external_edit(app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The whole path: a hand-edit, the poll thread, the bus, the socket."""
    config_path = _use_config_file(monkeypatch, tmp_path)
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        handshake = websocket.receive_json()
        watcher = _start_watcher_on_socket_loop(websocket, app_env)
        try:
            _write_config(config_path, "second-model")
            event = wait_for_event(websocket, "config.reloaded", max_events=400)
        finally:
            watcher.stop()

    assert event["session_id"] == ""
    assert event["event"]["revision"] > handshake["config_revision"]
    assert "second-model" in event["event"]["summary"]


def test_watcher_reaches_a_socket_watching_another_session(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config_path = _use_config_file(monkeypatch, tmp_path)
    watched_session = app_env.create_session()
    app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{watched_session}/ws") as websocket:
        consume_ws_handshake(websocket)
        watcher = _start_watcher_on_socket_loop(websocket, app_env)
        try:
            _write_config(config_path, "second-model")
            event = wait_for_event(websocket, "config.reloaded", max_events=400)
        finally:
            watcher.stop()

    assert event["event"]["revision"] >= 1


def test_watcher_keeps_the_running_session_client(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The product contract: a running session keeps the LLM client it built."""
    config_path = _use_config_file(monkeypatch, tmp_path)
    session_id = app_env.create_session()

    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        client_before = _session_llm_client(app_env, session_id)
        watcher = _start_watcher_on_socket_loop(websocket, app_env)
        try:
            _write_config(config_path, "second-model")
            event = wait_for_event(websocket, "config.reloaded", max_events=400)
        finally:
            watcher.stop()

        assert event["event"]["summary"] != "no model changes"
        assert _session_llm_client(app_env, session_id) is client_before


def test_check_config_change_returns_the_reload(
    app_env: AppEnv, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The summary the broadcast carries describes the new config."""
    from klaude_code.config import check_config_change

    config_path = _use_config_file(monkeypatch, tmp_path)
    load_config()

    _write_config(config_path, "second-model")
    reload_event = check_config_change()

    assert isinstance(reload_event, ConfigReload)
    assert "first-model" in reload_event.summary
    assert "second-model" in reload_event.summary


def _session_llm_client(app_env: AppEnv, session_id: str) -> Any:
    actor = app_env.runtime.session_registry.get_session_actor(session_id)
    assert actor is not None
    agent = actor.get_agent()
    assert agent is not None
    return agent.profile.llm_client
