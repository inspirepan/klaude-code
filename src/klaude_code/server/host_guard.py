"""Host header guard for the loopback TCP listener (DNS rebinding defence).

The web viewer has no authentication: it is reachable only from loopback. A
page on any origin can still make the *browser* resolve an attacker domain to
127.0.0.1 and talk to this server, so requests arriving over TCP must carry a
``Host`` of ``localhost`` or ``127.0.0.1``. Requests over the Unix socket are
exempt: httpx/websockets send whatever host the base URL had (the CLI uses
``http://klaude``, the TUI ``ws://klaude/...``), and reaching that socket
already requires local filesystem access.

Transport detection uses ``scope["server"]``, which uvicorn fills from the
listening socket's ``getsockname()`` (``uvicorn/protocols/utils.py``):

- Unix socket  -> ``(<socket path>, None)``  (port is always None)
- TCP socket   -> ``("127.0.0.1", <bound port>)``

Matching the bound web port exactly (rather than "port is not None") keeps
in-process ASGI clients such as Starlette's TestClient, whose scope says
``("testserver", 80)``, out of the check.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

ALLOWED_HOSTNAMES = frozenset({"localhost", "127.0.0.1"})

_REJECT_STATUS = 421  # Misdirected Request
_REJECT_BODY = b"klaude trace viewer only accepts Host: localhost or 127.0.0.1\n"


def hostname_from_host_header(raw: str) -> str:
    """Strip the optional port from a Host header value."""

    host = raw.strip()
    if host.startswith("["):  # IPv6 literal: [::1]:8765
        end = host.find("]")
        return host[1:end].lower() if end != -1 else ""
    return host.split(":", 1)[0].lower()


def is_allowed_host_header(raw: str) -> bool:
    return hostname_from_host_header(raw) in ALLOWED_HOSTNAMES


class HostHeaderGuardMiddleware:
    """Reject non-loopback Host headers on the web TCP port.

    Pure ASGI (like ``_EnvSyncMiddleware``): it only reads one header and
    passes the scope through, so it must not pay for ``BaseHTTPMiddleware``'s
    task group and body buffering.
    """

    def __init__(self, app: ASGIApp, *, web_port: int | None = None) -> None:
        self.app = app
        self._web_port = web_port

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self._guards(scope) and not is_allowed_host_header(_host_header(scope)):
            await self._reject(scope, receive, send)
            return
        await self.app(scope, receive, send)

    def _guards(self, scope: Scope) -> bool:
        if self._web_port is None or scope["type"] not in ("http", "websocket"):
            return False
        return self._is_web_tcp_scope(scope)

    def _is_web_tcp_scope(self, scope: Scope) -> bool:
        server = scope.get("server")
        if not isinstance(server, list | tuple) or len(server) != 2:
            return False
        return server[1] == self._web_port

    async def _reject(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # Uvicorn turns a close sent before accept into an HTTP rejection.
            await send({"type": "websocket.close", "code": 1008})
            return
        await send(
            {
                "type": "http.response.start",
                "status": _REJECT_STATUS,
                "headers": [
                    (b"content-type", b"text/plain; charset=utf-8"),
                    (b"content-length", str(len(_REJECT_BODY)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _REJECT_BODY})


def _host_header(scope: Scope) -> str:
    for name, value in scope.get("headers") or []:
        if name == b"host":
            return value.decode("latin-1")
    return ""
