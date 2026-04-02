from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from klaude_code.agent.runtime_llm import LLMClients
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus
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


def test_prepare_frontend_reinstalls_missing_dependencies_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_root = tmp_path / "repo"
    web_dir = project_root / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "package.json").write_text("{}", encoding="utf-8")
    (web_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    class _FakeProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = 0

        async def wait(self) -> int:
            return 0

    launches: list[tuple[str, ...]] = []
    ready_checks: list[str] = []
    terminated: list[_FakeProcess] = []

    async def _create_subprocess_exec(*args: str, **kwargs: str) -> _FakeProcess:
        launches.append(tuple(args))
        assert kwargs["cwd"] == str(web_dir)
        return _FakeProcess()

    async def _wait_until_ready(url: str, timeout_s: float = 10.0) -> bool:
        _ = timeout_s
        ready_checks.append(url)
        return len(ready_checks) == 2

    async def _terminate_process(process: _FakeProcess | None) -> None:
        if process is not None:
            terminated.append(process)

    def _should_auto_install_frontend(_project_root: Path) -> bool:
        return True

    monkeypatch.setattr(server, "_project_root", lambda: project_root)
    monkeypatch.setattr(server, "_find_pkg_manager", lambda: "pnpm")
    monkeypatch.setattr(server, "_should_auto_install_frontend", _should_auto_install_frontend)
    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", _create_subprocess_exec)
    monkeypatch.setattr(server, "_wait_until_ready", _wait_until_ready)
    monkeypatch.setattr(server, "_terminate_process", _terminate_process)

    plan = arun(server.prepare_frontend(host="127.0.0.1", backend_port=8765))

    assert plan.mode == "dev"
    assert plan.url == "http://127.0.0.1:8766/"
    assert launches == [
        ("pnpm", "run", "dev", "--host", "127.0.0.1", "--port", "8766", "--strictPort"),
        ("pnpm", "install", "--frozen-lockfile"),
        ("pnpm", "run", "dev", "--host", "127.0.0.1", "--port", "8766", "--strictPort"),
    ]
    assert len(terminated) == 1


def test_prepare_frontend_installs_when_declared_dependency_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_root = tmp_path / "repo"
    web_dir = project_root / "web"
    web_dir.mkdir(parents=True, exist_ok=True)
    (web_dir / "package.json").write_text(
        '{"dependencies": {"@fontsource-variable/ibm-plex-sans": "^5.2.8"}}',
        encoding="utf-8",
    )
    (web_dir / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'\n", encoding="utf-8")

    class _FakeProcess:
        def __init__(self) -> None:
            self.returncode: int | None = None

        def terminate(self) -> None:
            self.returncode = 0

        def kill(self) -> None:
            self.returncode = 0

        async def wait(self) -> int:
            return 0

    launches: list[tuple[str, ...]] = []

    async def _create_subprocess_exec(*args: str, **kwargs: str) -> _FakeProcess:
        launches.append(tuple(args))
        assert kwargs["cwd"] == str(web_dir)
        return _FakeProcess()

    async def _wait_until_ready(url: str, timeout_s: float = 10.0) -> bool:
        _ = (url, timeout_s)
        return True

    def _should_auto_install_frontend(_project_root: Path) -> bool:
        return True

    monkeypatch.setattr(server, "_project_root", lambda: project_root)
    monkeypatch.setattr(server, "_find_pkg_manager", lambda: "pnpm")
    monkeypatch.setattr(server, "_should_auto_install_frontend", _should_auto_install_frontend)
    monkeypatch.setattr(server.asyncio, "create_subprocess_exec", _create_subprocess_exec)
    monkeypatch.setattr(server, "_wait_until_ready", _wait_until_ready)

    plan = arun(server.prepare_frontend(host="127.0.0.1", backend_port=8765))

    assert plan.mode == "dev"
    assert plan.url == "http://127.0.0.1:8766/"
    assert launches == [
        ("pnpm", "install", "--frozen-lockfile"),
        ("pnpm", "run", "dev", "--host", "127.0.0.1", "--port", "8766", "--strictPort"),
    ]


def test_start_web_server_aborts_before_init_when_already_running(monkeypatch: pytest.MonkeyPatch) -> None:
    initialize_called = False

    async def _ensure_web_server_not_running(*, home_dir: Path) -> None:
        raise server.WebServerAlreadyRunningError(
            f"Web server is already running:\nsession meta relay socket already in use: {home_dir / 'socket'}"
        )

    async def _initialize_app_components(**_kwargs: object) -> None:
        nonlocal initialize_called
        initialize_called = True
        return None

    monkeypatch.setattr(server, "_ensure_web_server_not_running", _ensure_web_server_not_running)
    monkeypatch.setattr(server, "initialize_app_components", _initialize_app_components)

    with pytest.raises(server.WebServerAlreadyRunningError):
        arun(server.start_web_server(no_open=True))

    assert initialize_called is False


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
