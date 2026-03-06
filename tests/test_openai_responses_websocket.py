from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from typing import Any, cast

import pytest

from klaude_code.llm.openai_responses.client import ResponsesWebSocketTransport


class _CancelledConnection:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.close_calls = 0
        self.transport = _AbortTransport()

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self, decode: bool = False) -> bytes:
        raise asyncio.CancelledError

    async def close(self) -> None:
        self.close_calls += 1


class _AbortTransport:
    def __init__(self) -> None:
        self.abort_calls = 0

    def abort(self) -> None:
        self.abort_calls += 1


class _EventConnection:
    def __init__(self, events: list[dict[str, Any]]) -> None:
        self.sent: list[str] = []
        self.close_calls = 0
        self._events = events
        self._index = 0

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self, decode: bool = False) -> bytes:
        if self._index >= len(self._events):
            raise AssertionError("recv called after terminal event")
        event = self._events[self._index]
        self._index += 1
        return json.dumps(event).encode()

    async def close(self) -> None:
        self.close_calls += 1


class _TestTransport(ResponsesWebSocketTransport):
    def __init__(self, connections: Iterator[object]) -> None:
        super().__init__(client=cast(Any, object()))
        self._connections = connections

    def current_connection(self) -> object | None:
        return self._connection

    async def _ensure_connection(self):
        connection = self._connection
        if connection is None:
            connection = cast(Any, next(self._connections))
            self._connection = connection
        return connection


def test_responses_websocket_transport_reconnects_after_cancelled_stream() -> None:
    async def _run() -> None:
        cancelled = _CancelledConnection()
        completed = _EventConnection(
            [
                {
                    "type": "response.completed",
                    "response": {"id": "resp_2", "created_at": 0, "status": "completed", "output": []},
                }
            ]
        )
        transport = _TestTransport(iter([cancelled, completed]))

        with pytest.raises(asyncio.CancelledError):
            async for _ in transport.stream(cast(Any, {"model": "gpt-5.4", "input": []})):
                pass

        assert cancelled.transport.abort_calls == 1
        assert cancelled.close_calls == 0
        assert transport.current_connection() is None

        events = [event async for event in transport.stream(cast(Any, {"model": "gpt-5.4", "input": []}))]

        assert [event.type for event in events] == ["response.completed"]
        assert completed.close_calls == 0
        assert len(cancelled.sent) == 1
        assert len(completed.sent) == 1

    asyncio.run(_run())
