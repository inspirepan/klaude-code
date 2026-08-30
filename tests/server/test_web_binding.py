"""Dual binding: one uvicorn server on the Unix socket and a loopback TCP port.

These tests run a real uvicorn server (no TestClient) because the whole point
is what the transports look like on the wire: the Host guard keys off the
socket the request arrived on.
"""

from __future__ import annotations

import asyncio
import shutil
import socket
import tempfile
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from fastapi import Request, WebSocket

from klaude_code.agent.runtime import agent_ops
from klaude_code.agent.runtime import llm as agent_runtime
from klaude_code.agent.runtime.llm import LLMClients
from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EventBus
from klaude_code.server.app import create_app
from klaude_code.server.binding import bind_uds_socket, bind_web_socket, socket_port
from klaude_code.server.interaction import ServerInteractionHandler
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.state import ServerAppState

from .conftest import FakeLLMClient


@dataclass
class LiveServer:
    web_port: int
    socket_path: Path

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.web_port}"

    def tcp_get(self, path: str, *, host: str | None = None) -> httpx.Response:
        headers = {"Host": host} if host is not None else None
        # trust_env=False: a system HTTP proxy would otherwise route by the
        # Host header and answer instead of the server under test.
        with httpx.Client(trust_env=False, timeout=5.0) as client:
            return client.get(f"{self.base_url}{path}", headers=headers)

    def uds_get(self, path: str, *, base_url: str = "http://klaude") -> httpx.Response:
        transport = httpx.HTTPTransport(uds=str(self.socket_path))
        with httpx.Client(transport=transport, base_url=base_url, timeout=5.0) as client:
            return client.get(path)


@pytest.fixture
def short_tmp_dir() -> Iterator[Path]:
    """A directory short enough for an AF_UNIX path (108 bytes, ~104 on macOS).

    pytest's ``tmp_path`` embeds the test name and blows that budget.
    """

    path = Path(tempfile.mkdtemp(prefix="klw"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture
def live_server(isolated_home: Path, short_tmp_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[LiveServer]:
    fake_llm = FakeLLMClient()

    def _fake_default_clients(*_args: Any, **_kwargs: Any) -> LLMClients:
        return LLMClients(main=fake_llm, main_model_alias="fake")

    monkeypatch.setattr(agent_ops, "build_llm_clients", _fake_default_clients)
    monkeypatch.setattr(agent_runtime, "clone_llm_client", lambda client: client)

    socket_path = short_tmp_dir / "server.sock"
    uds_sock = bind_uds_socket(socket_path)
    # Port 0: never collide with a real klaude server on 8765.
    web_sock = bind_web_socket(start_port=0)
    assert web_sock is not None
    web_port = socket_port(web_sock)

    async def _state_initializer() -> ServerAppState:
        event_bus = EventBus()
        return ServerAppState(
            runtime=RuntimeFacade(event_bus, LLMClients(main=fake_llm, main_model_alias="fake")),
            event_bus=event_bus,
            interaction_handler=ServerInteractionHandler(),
            home_dir=isolated_home,
            lifecycle=ServerLifecycle(socket_path=socket_path),
        )

    async def _state_shutdown(state: ServerAppState) -> None:
        await state.runtime.stop()

    app = create_app(
        home_dir=isolated_home,
        state_initializer=_state_initializer,
        state_shutdown=_state_shutdown,
        web_port=web_port,
    )

    async def _scope_probe(request: Request) -> dict[str, Any]:
        """Expose the ASGI scope fields the Host guard keys off."""
        return {"server": request.scope.get("server"), "client": request.scope.get("client")}

    async def _ws_probe(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    app.add_api_route("/__scope_probe__", _scope_probe, methods=["GET"], include_in_schema=False)
    app.add_api_websocket_route("/__ws_probe__", _ws_probe)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", ws_ping_interval=None, ws_ping_timeout=None))

    thread = threading.Thread(target=lambda: asyncio.run(server.serve(sockets=[uds_sock, web_sock])), daemon=True)
    thread.start()
    deadline = time.monotonic() + 20.0
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "uvicorn did not start"

    try:
        yield LiveServer(web_port=web_port, socket_path=socket_path)
    finally:
        server.should_exit = True
        thread.join(timeout=20.0)
        uds_sock.close()
        web_sock.close()
        socket_path.unlink(missing_ok=True)


def test_status_over_tcp_reports_the_bound_web_port(live_server: LiveServer) -> None:
    response = live_server.tcp_get("/api/server/status")
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["web_port"] == live_server.web_port
    assert payload["web_url"] == f"http://127.0.0.1:{live_server.web_port}"


def test_uds_still_serves_the_same_app(live_server: LiveServer) -> None:
    """The CLI's `http://klaude` base URL keeps working: no Host check on UDS."""

    response = live_server.uds_get("/api/server/status")
    assert response.status_code == 200
    assert response.json()["web_port"] == live_server.web_port


def test_uds_accepts_an_arbitrary_host_header(live_server: LiveServer) -> None:
    response = live_server.uds_get("/api/server/status", base_url="http://evil.com")
    assert response.status_code == 200


def test_session_list_is_reachable_over_tcp(live_server: LiveServer) -> None:
    response = live_server.tcp_get("/api/headless/sessions")
    assert response.status_code == 200
    assert response.json()["sessions"] == []


def test_session_list_accepts_the_viewer_query_over_tcp(live_server: LiveServer) -> None:
    """The viewer's list page passes include_children + an explicit limit."""

    response = live_server.tcp_get("/api/headless/sessions?include_children=1&limit=100")
    assert response.status_code == 200
    assert response.json()["sessions"] == []


def test_web_api_routes_are_reachable_over_tcp(live_server: LiveServer) -> None:
    # 404 (not 421/405) proves the request reached the ledger route itself.
    assert live_server.tcp_get("/api/web/sessions/nosuch/meta").status_code == 404
    assert live_server.tcp_get("/api/web/sessions/nosuch/history").status_code == 404
    assert live_server.tcp_get("/api/web/sessions/nosuch/system-context").status_code == 404
    assert live_server.tcp_get("/api/web/sessions/nosuch/search?q=x").status_code == 404


def test_web_api_routes_honour_the_host_guard(live_server: LiveServer) -> None:
    for path in (
        "/api/web/sessions/nosuch/meta",
        "/api/web/sessions/nosuch/system-context",
        "/api/web/sessions/nosuch/search?q=x",
    ):
        assert live_server.tcp_get(path, host="evil.com").status_code == 421


@pytest.mark.parametrize("host", ["evil.com", "127.0.0.1.nip.io", "attacker.example:1234"])
def test_tcp_rejects_foreign_host_headers(live_server: LiveServer, host: str) -> None:
    response = live_server.tcp_get("/api/server/status", host=host)
    assert response.status_code == 421


def test_tcp_accepts_loopback_host_headers(live_server: LiveServer) -> None:
    for host in (f"localhost:{live_server.web_port}", "127.0.0.1", f"127.0.0.1:{live_server.web_port}", "localhost"):
        assert live_server.tcp_get("/api/server/status", host=host).status_code == 200


def test_websocket_handshake_honours_the_host_guard(live_server: LiveServer) -> None:
    """Raw handshake: the websockets client cannot forge a lone Host header."""

    accepted = _ws_handshake_status(live_server.web_port, f"127.0.0.1:{live_server.web_port}")
    assert "101" in accepted
    rejected = _ws_handshake_status(live_server.web_port, "evil.com")
    assert "101" not in rejected


def _ws_handshake_status(port: int, host_header: str, path: str = "/__ws_probe__") -> str:
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    with socket.create_connection(("127.0.0.1", port), timeout=5.0) as sock:
        sock.sendall(request.encode("ascii"))
        response = sock.recv(4096)
    return response.split(b"\r\n", 1)[0].decode("latin-1")


def test_uds_scope_has_no_port_and_tcp_scope_has_the_web_port(live_server: LiveServer) -> None:
    """Pin the scope shape the Host guard relies on (see server/host_guard.py)."""

    scopes = live_server.tcp_get("/__scope_probe__").json()
    assert scopes["server"] == ["127.0.0.1", live_server.web_port]
    uds_scope = live_server.uds_get("/__scope_probe__").json()
    assert uds_scope["server"][0] == str(live_server.socket_path)
    assert uds_scope["server"][1] is None


# -- socket binding units --


def test_web_socket_falls_back_to_the_next_free_port() -> None:
    with _occupied_port() as (busy_port, _busy):
        sock = bind_web_socket(start_port=busy_port, scan_limit=5)
        assert sock is not None
        try:
            # The exact port depends on what else the machine holds; what
            # matters is that a busy start port shifts upward instead of failing.
            assert busy_port < socket_port(sock) <= busy_port + 5
        finally:
            sock.close()


def test_web_socket_returns_none_when_every_candidate_is_busy() -> None:
    with _occupied_port() as (busy_port, _busy):
        assert bind_web_socket(start_port=busy_port, scan_limit=0) is None


def test_uds_socket_replaces_a_stale_socket_file(short_tmp_dir: Path) -> None:
    socket_path = short_tmp_dir / "run" / "server.sock"
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    socket_path.parent.mkdir(parents=True)
    stale.bind(str(socket_path))
    stale.close()

    sock = bind_uds_socket(socket_path)
    try:
        assert socket_path.is_socket()
        assert sock.getsockname() == str(socket_path)
    finally:
        sock.close()
        socket_path.unlink(missing_ok=True)


class _occupied_port:
    """Hold a listening socket on an ephemeral port for the duration of the test."""

    def __enter__(self) -> tuple[int, socket.socket]:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        return int(self._sock.getsockname()[1]), self._sock

    def __exit__(self, *_exc: object) -> None:
        self._sock.close()
