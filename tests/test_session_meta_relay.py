from __future__ import annotations

import asyncio
import socket
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

from klaude_code.core.control.session_meta_relay import (
    SessionMetaRelayMessage,
    SessionMetaRelayPublisher,
    SessionMetaRelayServer,
    session_meta_relay_socket_path,
)

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_session_meta_relay_round_trips_upsert(tmp_path: Path) -> None:
    async def _test() -> None:
        socket_path = session_meta_relay_socket_path(home_dir=tmp_path)
        received: list[SessionMetaRelayMessage] = []
        relay_server = SessionMetaRelayServer(socket_path=socket_path, on_message=received.append)
        relay_publisher = SessionMetaRelayPublisher(socket_path=socket_path)

        await relay_server.start()
        try:
            relay_publisher.publish_upsert("s1", {"id": "s1", "title": "hello"})
            deadline = asyncio.get_running_loop().time() + 1.0
            while not received and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.01)
        finally:
            relay_publisher.close()
            await relay_server.aclose()

        assert received == [
            SessionMetaRelayMessage(kind="upsert", session_id="s1", meta={"id": "s1", "title": "hello"})
        ]

    arun(_test())


def test_session_meta_relay_server_closes_idle_connections_on_shutdown(tmp_path: Path) -> None:
    async def _test() -> None:
        socket_path = session_meta_relay_socket_path(home_dir=tmp_path)
        relay_server = SessionMetaRelayServer(socket_path=socket_path, on_message=lambda _message: None)

        await relay_server.start()
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        conn.connect(str(socket_path))
        try:
            await asyncio.wait_for(relay_server.aclose(), timeout=1.0)
        finally:
            conn.close()

    arun(_test())
