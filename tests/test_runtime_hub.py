from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.runtime_hub import GLOBAL_RUNTIME_ID, RuntimeHub
from klaude_code.protocol import op
from klaude_code.protocol.message import UserInputPayload

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_runtime_hub_preserves_in_session_order() -> None:
    async def _test() -> None:
        handled: list[tuple[str | None, str]] = []
        done = asyncio.Event()

        async def _handle(submission: op.Submission) -> None:
            sid = getattr(submission.operation, "session_id", None)
            handled.append((sid, submission.id))
            if len(handled) >= 3:
                done.set()

        hub = RuntimeHub(handle_submission=_handle)
        s1_first = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="a"))
        s2_only = op.RunAgentOperation(session_id="s2", input=UserInputPayload(text="b"))
        s1_second = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="c"))

        await hub.submit(op.Submission(id=s1_first.id, operation=s1_first))
        await hub.submit(op.Submission(id=s2_only.id, operation=s2_only))
        await hub.submit(op.Submission(id=s1_second.id, operation=s1_second))

        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        s1_seen = [submission_id for sid, submission_id in handled if sid == "s1"]
        assert s1_seen == [s1_first.id, s1_second.id]

    arun(_test())


def test_runtime_hub_routes_global_interrupt_to_global_runtime() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        async def _handle(_submission: op.Submission) -> None:
            started.set()

        hub = RuntimeHub(handle_submission=_handle)
        operation = op.InterruptOperation(target_session_id=None)

        await hub.submit(op.Submission(id=operation.id, operation=operation))
        await asyncio.wait_for(started.wait(), timeout=1.0)

        assert hub.has_runtime(GLOBAL_RUNTIME_ID)

        with contextlib.suppress(Exception):
            await hub.stop()

    arun(_test())
