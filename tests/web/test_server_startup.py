from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from klaude_code.core.agent.runtime_llm import LLMClients
from klaude_code.core.control.event_bus import EventBus
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.session.session import close_default_store
from klaude_code.web import server
from klaude_code.web.app import create_app
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.state import WebAppState

from .conftest import FakeLLMClient, arun


def test_default_startup_opens_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def _capture_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(server.webbrowser, "open", _capture_open)

    server.open_browser("http://127.0.0.1:8765/", no_open=False)
    assert opened == ["http://127.0.0.1:8765/"]


def test_no_open_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def _capture_open(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(server.webbrowser, "open", _capture_open)

    server.open_browser("http://127.0.0.1:8765/", no_open=True)
    assert opened == []


def test_fallback_to_static_when_no_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    web_dir = project_root / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "package.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(server, "_project_root", lambda: project_root)

    def _which(_name: str) -> None:
        return None

    monkeypatch.setattr(server.shutil, "which", _which)

    plan = arun(server.prepare_frontend(host="127.0.0.1", backend_port=8765))
    assert plan.mode == "static"
    assert plan.process is None
    assert plan.url == "http://127.0.0.1:8765/"


def test_packaged_env_serves_static(tmp_path: Path) -> None:
    static_dir = tmp_path / "dist"
    static_dir.mkdir(parents=True, exist_ok=True)
    (static_dir / "index.html").write_text("<html><body>ok</body></html>", encoding="utf-8")

    async def _state_initializer() -> WebAppState:
        event_bus = EventBus()
        runtime = RuntimeFacade(
            event_bus,
            LLMClients(main=FakeLLMClient(), main_model_alias="fake"),
        )
        return WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=WebInteractionHandler(),
            work_dir=tmp_path,
            home_dir=tmp_path,
        )

    async def _state_shutdown(state: WebAppState) -> None:
        await state.runtime.stop()
        await close_default_store()

    app = create_app(
        work_dir=tmp_path,
        home_dir=tmp_path,
        static_dir=static_dir,
        state_initializer=_state_initializer,
        state_shutdown=_state_shutdown,
    )
    with TestClient(app) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert "ok" in response.text
