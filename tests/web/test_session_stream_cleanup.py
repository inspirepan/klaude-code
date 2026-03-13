from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable
from types import SimpleNamespace
from typing import Any, cast

import pytest
from starlette.requests import Request

from klaude_code.web.routes.sessions import stream_sessions
from klaude_code.web.session_live import SessionEventStream
from klaude_code.web.state import WebAppState

from .conftest import arun


class _Request:
    async def is_disconnected(self) -> bool:
        return False


async def _next_chunk(iterator: AsyncIterator[str]) -> str:
    return await anext(iterator)


def test_session_stream_releases_subscription_when_cancelled() -> None:
    async def _run() -> None:
        stream = SessionEventStream()
        state = cast(Any, SimpleNamespace(session_live=SimpleNamespace(stream=stream)))
        response = await stream_sessions(cast(Request, _Request()), state=cast(WebAppState, state))
        iterator = cast(AsyncIterator[str], response.body_iterator)
        existing_tasks = set(asyncio.all_tasks())

        try:
            receive_task = asyncio.create_task(_next_chunk(iterator))
            await asyncio.sleep(0)
            await asyncio.sleep(0)

            assert stream.subscriber_count() == 1

            receive_task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await receive_task

            await asyncio.sleep(0)
            await asyncio.sleep(0)

            assert stream.subscriber_count() == 0
        finally:
            aclose = cast(Callable[[], Awaitable[object]] | None, getattr(iterator, "aclose", None))
            if callable(aclose):
                with contextlib.suppress(Exception):
                    await aclose()

            pending_tasks = [
                task
                for task in asyncio.all_tasks()
                if task not in existing_tasks and task is not asyncio.current_task() and not task.done()
            ]
            for task in pending_tasks:
                task.cancel()
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

    arun(_run())
