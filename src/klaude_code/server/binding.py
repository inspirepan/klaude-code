"""Listening sockets for the server: the CLI/TUI Unix socket and the web TCP port.

Both sockets are bound here and handed to a single ``uvicorn.Server.serve``
call so the ASGI lifespan (and therefore the whole runtime) starts once. When
``sockets=`` is passed uvicorn skips its own ``uds``/host-port branches, so
unlinking the stale socket file, the socket file mode, and the port scan are
this module's job.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

# The old debug log viewer used to squat on 8765; it was removed with the web
# viewer's arrival, so the port is free for the browser UI.
DEFAULT_WEB_PORT = 8765
WEB_HOST = "127.0.0.1"
# Bounded scan: 8765..8815. Beyond that something is wrong with the machine,
# and an unbounded scan would hand the user an unpredictable URL.
WEB_PORT_SCAN_LIMIT = 50


def bind_uds_socket(socket_path: Path) -> socket.socket:
    """Bind the server's Unix socket, replacing any stale file at that path.

    The caller holds the singleton flock, so an existing socket file has no
    live owner and is safe to unlink.
    """

    socket_path.parent.mkdir(parents=True, exist_ok=True)
    socket_path.unlink(missing_ok=True)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(socket_path))
    except OSError:
        sock.close()
        raise
    # Mirrors uvicorn's own uds branch (0o666); the 0700 run directory is what
    # actually keeps other users out.
    os.chmod(socket_path, 0o666)
    return sock


def bind_web_socket(
    *,
    host: str = WEB_HOST,
    start_port: int = DEFAULT_WEB_PORT,
    scan_limit: int = WEB_PORT_SCAN_LIMIT,
) -> socket.socket | None:
    """Bind the loopback TCP socket for the web viewer, or None if none is free.

    Tries ``start_port`` first and walks upward, so a second machine-local
    process (or a leftover listener) only shifts the URL instead of failing
    the whole server. ``start_port=0`` asks the kernel for an ephemeral port
    (tests).
    """

    if start_port == 0:
        return _bind_one(host, 0)
    for port in range(start_port, start_port + scan_limit + 1):
        sock = _bind_one(host, port)
        if sock is not None:
            return sock
    return None


def _bind_one(host: str, port: int) -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Without SO_REUSEADDR a reload can hit TIME_WAIT from a just-closed
    # browser connection and fall through to the next port for no reason.
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError:
        sock.close()
        return None
    return sock


def socket_port(sock: socket.socket) -> int:
    return int(sock.getsockname()[1])


def web_url(port: int, *, host: str = WEB_HOST) -> str:
    return f"http://{host}:{port}"
