"""Unit coverage for the Host header guard (wire-level tests live in test_web_binding)."""

from __future__ import annotations

from typing import Any

import pytest
from starlette.types import Message, Receive, Scope, Send

from klaude_code.server.host_guard import HostHeaderGuardMiddleware, is_allowed_host_header


@pytest.mark.parametrize(
    "raw",
    ["localhost", "localhost:8765", "127.0.0.1", "127.0.0.1:8765", "LOCALHOST:8765"],
)
def test_loopback_host_headers_are_allowed(raw: str) -> None:
    assert is_allowed_host_header(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "evil.com",
        "evil.com:8765",
        "127.0.0.1.nip.io",  # resolves to 127.0.0.1 but is an attacker's name
        "localhost.evil.com",
        "[::1]:8765",  # only 127.0.0.1 is bound, so ::1 is never legitimate
        "192.168.1.10:8765",
    ],
)
def test_foreign_host_headers_are_rejected(raw: str) -> None:
    assert not is_allowed_host_header(raw)


async def _collect(middleware: HostHeaderGuardMiddleware, scope: Scope) -> list[Message]:
    sent: list[Message] = []

    async def _receive() -> Message:
        return {"type": "http.request"}

    async def _send(message: Message) -> None:
        sent.append(message)

    await middleware(scope, _receive, _send)
    return sent


def _scope(server: Any, host: bytes = b"evil.com", scope_type: str = "http") -> Scope:
    return {"type": scope_type, "server": server, "headers": [(b"host", host)]}


async def _inner_app(scope: Scope, receive: Receive, send: Send) -> None:
    del scope, receive
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"passed through"})


def test_guard_matrix() -> None:
    """One event loop for the whole matrix; the middleware has no state to reset."""

    import asyncio

    guard = HostHeaderGuardMiddleware(_inner_app, web_port=8765)

    async def _run() -> None:
        # TCP scope on the web port with a foreign Host -> rejected.
        sent = await _collect(guard, _scope(("127.0.0.1", 8765)))
        assert sent[0]["status"] == 421

        # Same scope with an allowed Host -> passed through.
        sent = await _collect(guard, _scope(("127.0.0.1", 8765), host=b"localhost:8765"))
        assert sent[0]["status"] == 200

        # Unix socket scope: uvicorn reports (path, None); Host is arbitrary.
        sent = await _collect(guard, _scope(("/run/klaude/server.sock", None)))
        assert sent[0]["status"] == 200

        # An in-process ASGI client (TestClient) is not the web listener.
        sent = await _collect(guard, _scope(("testserver", 80)))
        assert sent[0]["status"] == 200

        # No web listener at all -> the guard is inert.
        off = HostHeaderGuardMiddleware(_inner_app, web_port=None)
        sent = await _collect(off, _scope(("127.0.0.1", 8765)))
        assert sent[0]["status"] == 200

        # Websocket scopes are closed rather than answered with HTTP.
        sent = await _collect(guard, _scope(("127.0.0.1", 8765), scope_type="websocket"))
        assert sent[0]["type"] == "websocket.close"

    asyncio.run(_run())
