from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.runtime_hub import GLOBAL_RUNTIME_ID, RuntimeHub
from klaude_code.protocol import op
from klaude_code.protocol.llm_param import Thinking
from klaude_code.protocol.message import UserInputPayload

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_runtime_hub_preserves_in_session_order() -> None:
    async def _test() -> None:
        handled: list[tuple[str | None, str]] = []
        done = asyncio.Event()

        async def _handle(operation: op.Operation) -> None:
            sid = getattr(operation, "session_id", None)
            handled.append((sid, operation.id))
            if len(handled) >= 3:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject when session is idle")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)
        s1_first = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        s2_only = op.ChangeThinkingOperation(session_id="s2", thinking=Thinking(type="enabled", budget_tokens=20))
        s1_second = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=30))

        await hub.submit(s1_first)
        await hub.submit(s2_only)
        await hub.submit(s1_second)

        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        s1_seen = [submission_id for sid, submission_id in handled if sid == "s1"]
        assert s1_seen == [s1_first.id, s1_second.id]

    arun(_test())


def test_runtime_hub_routes_global_interrupt_to_global_runtime() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        async def _handle(_operation: op.Operation) -> None:
            started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)
        operation = op.InterruptOperation(target_session_id=None)

        await hub.submit(operation)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        assert hub.has_runtime(GLOBAL_RUNTIME_ID)

        with contextlib.suppress(Exception):
            await hub.stop()

    arun(_test())


def test_runtime_hub_rejects_second_root_while_first_is_active() -> None:
    async def _test() -> None:
        handled: list[str] = []
        rejected: list[tuple[str, str | None]] = []
        second_rejected = asyncio.Event()

        first_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        second_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="second"))

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)

        async def _reject(operation: op.Operation, active_root_operation_id: str | None) -> None:
            rejected.append((operation.id, active_root_operation_id))
            second_rejected.set()

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(first_op)
        await hub.submit(second_op)
        await asyncio.wait_for(second_rejected.wait(), timeout=1.0)

        hub.mark_operation_completed(first_op.id)
        hub.mark_operation_completed(second_op.id)
        await hub.stop()

        assert handled == [first_op.id]
        assert rejected == [(second_op.id, first_op.id)]

    arun(_test())


def test_runtime_hub_allows_interrupt_while_root_is_active() -> None:
    async def _test() -> None:
        handled: list[str] = []
        done = asyncio.Event()
        first_started = asyncio.Event()

        first_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        interrupt_op = op.InterruptOperation(target_session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
            if operation.id == interrupt_op.id:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(first_op)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await hub.submit(interrupt_op)
        await asyncio.wait_for(done.wait(), timeout=1.0)

        hub.mark_operation_completed(first_op.id)
        hub.mark_operation_completed(interrupt_op.id)
        await hub.stop()

        assert handled == [first_op.id, interrupt_op.id]

    arun(_test())


def test_runtime_hub_allows_new_root_after_completion_marked() -> None:
    async def _test() -> None:
        handled: list[str] = []
        done = asyncio.Event()
        hub: RuntimeHub | None = None

        first_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        second_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="second"))

        async def _handle(operation: op.Operation) -> None:
            if hub is None:
                raise AssertionError("hub should be initialized")
            handled.append(operation.id)
            hub.mark_operation_completed(operation.id)
            if len(handled) == 2:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("second root should be accepted after completion")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(first_op)
        await hub.submit(second_op)

        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        assert handled == [first_op.id, second_op.id]

    arun(_test())


def test_runtime_hub_prioritizes_control_queue_over_normal_queue() -> None:
    async def _test() -> None:
        handled: list[str] = []
        done = asyncio.Event()
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        first_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        second_normal = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=20))
        control_interrupt = op.InterruptOperation(target_session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
                await release_first.wait()
            if len(handled) == 3:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("non-root/control ops should not be rejected")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(first_op)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await hub.submit(second_normal)
        await hub.submit(control_interrupt)

        release_first.set()
        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        assert handled == [first_op.id, control_interrupt.id, second_normal.id]

    arun(_test())


def test_runtime_hub_enforces_control_burst_fairness() -> None:
    async def _test() -> None:
        handled: list[str] = []
        done = asyncio.Event()
        first_started = asyncio.Event()
        release_first = asyncio.Event()

        first_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        normal_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=20))
        control_1 = op.InterruptOperation(target_session_id="s1")
        control_2 = op.InterruptOperation(target_session_id="s1")
        control_3 = op.InterruptOperation(target_session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
                await release_first.wait()
            if len(handled) == 5:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("non-root/control ops should not be rejected")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject, control_burst_quota=2)

        await hub.submit(first_op)
        await asyncio.wait_for(first_started.wait(), timeout=1.0)
        await hub.submit(control_1)
        await hub.submit(control_2)
        await hub.submit(control_3)
        await hub.submit(normal_op)

        release_first.set()
        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        assert handled == [first_op.id, control_1.id, control_2.id, normal_op.id, control_3.id]

    arun(_test())


def test_runtime_hub_tracks_pending_request_state_per_session() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        async def _handle(operation: op.Operation) -> None:
            if operation.id:
                started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)
        warmup_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))

        await hub.submit(warmup_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        hub.mark_request_state(session_id="s1", request_id="r1", is_pending=True)
        assert hub.pending_request_count("s1") == 1

        hub.mark_request_state(session_id="s1", request_id="r1", is_pending=False)
        assert hub.pending_request_count("s1") == 0

        await hub.stop()

    arun(_test())


def test_runtime_hub_idle_runtime_ids_reflect_active_and_pending_state() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        root_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="work"))

        async def _handle(operation: op.Operation) -> None:
            if operation.id == root_op.id:
                started.set()
                await release.wait()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(root_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert "s1" not in hub.idle_runtime_ids()

        hub.mark_request_state(session_id="s1", request_id="r1", is_pending=True)
        assert "s1" not in hub.idle_runtime_ids()

        release.set()
        hub.mark_operation_completed(root_op.id)
        await asyncio.sleep(0)
        assert "s1" not in hub.idle_runtime_ids()

        hub.mark_request_state(session_id="s1", request_id="r1", is_pending=False)
        assert "s1" in hub.idle_runtime_ids()

        await hub.stop()

    arun(_test())


def test_runtime_hub_tracks_session_local_config_by_session() -> None:
    async def _test() -> None:
        processed = asyncio.Event()
        processed_count = 0
        hub: RuntimeHub | None = None

        model_op = op.ChangeModelOperation(session_id="s1", model_name="model-a")
        thinking_op = op.ChangeThinkingOperation(
            session_id="s1",
            thinking=Thinking(type="enabled", budget_tokens=99),
        )
        compact_op = op.ChangeCompactModelOperation(session_id="s2", model_name="compact-x")
        sub_model_op = op.ChangeSubAgentModelOperation(
            session_id="s2",
            sub_agent_type="explore",
            model_name="model-sub",
        )

        async def _handle(operation: op.Operation) -> None:
            nonlocal processed_count
            if hub is None:
                raise AssertionError("hub should be initialized")
            hub.apply_operation_effect(operation)
            processed_count += 1
            if processed_count == 4:
                processed.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("config operations should not be rejected")

        hub = RuntimeHub(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(model_op)
        await hub.submit(thinking_op)
        await hub.submit(compact_op)
        await hub.submit(sub_model_op)

        await asyncio.wait_for(processed.wait(), timeout=1.0)

        s1 = hub.config_snapshot("s1")
        s2 = hub.config_snapshot("s2")
        assert s1 is not None
        assert s2 is not None

        assert s1.model_name == "model-a"
        assert s1.thinking is not None
        assert s1.thinking.budget_tokens == 99

        assert s2.compact_model == "compact-x"
        assert s2.sub_agent_models == {"explore": "model-sub"}

        await hub.stop()

    arun(_test())
