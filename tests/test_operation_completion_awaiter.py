from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.app.runtime_facade import OperationCompletionAwaiter
from klaude_code.control.event_bus import EventBus
from klaude_code.protocol import events

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_operation_completion_awaiter_resolves_on_operation_finished() -> None:
    async def _test() -> None:
        bus = EventBus()
        awaiter = OperationCompletionAwaiter(bus)
        awaiter.register("op1")

        wait_task = asyncio.create_task(awaiter.wait_for("op1"))
        await asyncio.sleep(0)

        await bus.publish(
            events.OperationFinishedEvent(
                session_id="s1",
                operation_id="op1",
                operation_type="run_agent",
                status="completed",
            ),
            operation_id="op1",
        )

        await asyncio.wait_for(wait_task, timeout=1.0)
        await awaiter.stop()

    arun(_test())


def test_operation_completion_awaiter_resolves_on_operation_rejected() -> None:
    async def _test() -> None:
        bus = EventBus()
        awaiter = OperationCompletionAwaiter(bus)
        awaiter.register("op2")

        wait_task = asyncio.create_task(awaiter.wait_for("op2"))
        await asyncio.sleep(0)

        await bus.publish(
            events.OperationRejectedEvent(
                session_id="s1",
                operation_id="op2",
                operation_type="run_agent",
                reason="session_busy",
                active_task_id="task1",
            ),
            operation_id="op2",
        )

        await asyncio.wait_for(wait_task, timeout=1.0)
        await awaiter.stop()

    arun(_test())
