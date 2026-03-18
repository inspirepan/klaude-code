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


class _ConcurrentRecvConnection(_EventConnection):
    def __init__(self, events: list[dict[str, Any]], started: asyncio.Event, release: asyncio.Event) -> None:
        super().__init__(events)
        self._started = started
        self._release = release
        self._receiving = False

    async def recv(self, decode: bool = False) -> bytes:
        if self._receiving:
            raise AssertionError("recv called concurrently on the same websocket")
        self._receiving = True
        self._started.set()
        await self._release.wait()
        try:
            return await super().recv(decode=decode)
        finally:
            self._receiving = False


class _TestTransport(ResponsesWebSocketTransport):
    def __init__(self, connections: Iterator[object]) -> None:
        super().__init__(client=cast(Any, object()))
        self._connections = connections

    async def _open_connection(self):
        return cast(Any, next(self._connections))


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

        events = [event async for event in transport.stream(cast(Any, {"model": "gpt-5.4", "input": []}))]

        assert [event.type for event in events] == ["response.completed"]
        assert completed.close_calls == 1
        assert len(cancelled.sent) == 1
        assert len(completed.sent) == 1

    asyncio.run(_run())


def test_responses_websocket_transport_uses_separate_connections_for_concurrent_streams() -> None:
    async def _collect_events(transport: ResponsesWebSocketTransport, payload: dict[str, Any]) -> list[str]:
        return [event.type async for event in transport.stream(cast(Any, payload))]

    async def _run() -> None:
        started_one = asyncio.Event()
        started_two = asyncio.Event()
        release = asyncio.Event()
        connection_one = _ConcurrentRecvConnection(
            [
                {
                    "type": "response.completed",
                    "response": {"id": "resp_1", "created_at": 0, "status": "completed", "output": []},
                }
            ],
            started_one,
            release,
        )
        connection_two = _ConcurrentRecvConnection(
            [
                {
                    "type": "response.completed",
                    "response": {"id": "resp_2", "created_at": 0, "status": "completed", "output": []},
                }
            ],
            started_two,
            release,
        )
        transport = _TestTransport(iter([connection_one, connection_two]))

        stream_one = asyncio.create_task(_collect_events(transport, {"model": "gpt-5.4", "input": []}))
        stream_two = asyncio.create_task(_collect_events(transport, {"model": "gpt-5.4", "input": []}))

        await asyncio.wait_for(asyncio.gather(started_one.wait(), started_two.wait()), timeout=1)
        release.set()

        events_one, events_two = await asyncio.gather(stream_one, stream_two)

        assert events_one == ["response.completed"]
        assert events_two == ["response.completed"]
        assert len(connection_one.sent) == 1
        assert len(connection_two.sent) == 1
        assert connection_one.close_calls == 1
        assert connection_two.close_calls == 1

    asyncio.run(_run())
