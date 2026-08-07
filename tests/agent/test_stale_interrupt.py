from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from klaude_code.agent.runtime.agent_ops import AgentOperationHandler


def test_interrupt_ignores_a_newer_active_operation() -> None:
    async def _test() -> None:
        handler: Any = object.__new__(AgentOperationHandler)
        runtime = SimpleNamespace(
            snapshot=lambda: SimpleNamespace(
                active_root_task=SimpleNamespace(operation_id="queued-turn"),
            )
        )
        handler._get_session_actor = lambda _session_id: runtime

        async def _unexpected_emit(_event: Any) -> None:
            raise AssertionError("a stale interrupt must not emit events")

        handler._emit_event = _unexpected_emit

        interrupted = await handler.interrupt("session", expected_operation_id="finished-turn")
        assert interrupted is False

    asyncio.run(_test())
