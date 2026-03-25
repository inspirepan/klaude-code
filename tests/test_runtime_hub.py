from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, TypeVar

from klaude_code.core.control.session_registry import SessionRegistry
from klaude_code.core.control.user_interaction import PendingUserInteractionRequest
from klaude_code.protocol import op, user_interaction
from klaude_code.protocol.llm_param import Thinking
from klaude_code.protocol.message import UserInputPayload

T = TypeVar("T")


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _pending_request(request_id: str, session_id: str) -> PendingUserInteractionRequest:
    return PendingUserInteractionRequest(
        request_id=request_id,
        session_id=session_id,
        source="tool",
        tool_call_id=None,
        payload=user_interaction.AskUserQuestionRequestPayload(
            questions=[
                user_interaction.AskUserQuestionQuestion(
                    id="q1",
                    header="h",
                    question="q",
                    options=[
                        user_interaction.AskUserQuestionOption(id="o1", label="A", description="d"),
                        user_interaction.AskUserQuestionOption(id="o2", label="B", description="d"),
                    ],
                )
            ]
        ),
    )


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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
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


def test_runtime_hub_routes_interrupt_to_target_session_runtime() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        async def _handle(_operation: op.Operation) -> None:
            started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        operation = op.InterruptOperation(session_id="s1")

        await hub.submit(operation)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        assert hub.has_session_actor("s1")

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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

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
        interrupt_op = op.InterruptOperation(session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
            if operation.id == interrupt_op.id:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

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
        hub: SessionRegistry | None = None

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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

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
        control_interrupt = op.InterruptOperation(session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
                await release_first.wait()
            if len(handled) == 3:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("non-root/control ops should not be rejected")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

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
        control_1 = op.InterruptOperation(session_id="s1")
        control_2 = op.InterruptOperation(session_id="s1")
        control_3 = op.InterruptOperation(session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            handled.append(operation.id)
            if operation.id == first_op.id:
                first_started.set()
                await release_first.wait()
            if len(handled) == 5:
                done.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("non-root/control ops should not be rejected")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject, control_burst_quota=2)

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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        warmup_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))

        await hub.submit(warmup_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        req = _pending_request("r1", "s1")
        task = asyncio.create_task(hub.request_user_interaction(req))
        await asyncio.sleep(0)
        assert hub.pending_request_count("s1") == 1

        hub.respond_user_interaction(
            request_id=req.request_id,
            session_id=req.session_id,
            response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )
        response = await task
        assert response.status == "cancelled"
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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(root_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        assert "s1" not in hub.idle_runtime_ids()

        req = _pending_request("r1", "s1")
        pending_task = asyncio.create_task(hub.request_user_interaction(req))
        await asyncio.sleep(0)
        assert "s1" not in hub.idle_runtime_ids()

        release.set()
        hub.mark_operation_completed(root_op.id)
        await asyncio.sleep(0)
        assert "s1" not in hub.idle_runtime_ids()

        assert hub.cancel_pending_interactions(session_id="s1")
        with contextlib.suppress(asyncio.CancelledError):
            await pending_task
        assert "s1" in hub.idle_runtime_ids()

        await hub.stop()

    arun(_test())


def test_runtime_hub_resolve_one_request_keeps_other_pending() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        async def _handle(operation: op.Operation) -> None:
            if operation.id:
                started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        warmup_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        await hub.submit(warmup_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        req1 = _pending_request("r1", "s1")
        req2 = _pending_request("r2", "s1")
        first = asyncio.create_task(hub.request_user_interaction(req1))
        second = asyncio.create_task(hub.request_user_interaction(req2))
        await asyncio.sleep(0)

        hub.respond_user_interaction(
            request_id=req1.request_id,
            session_id=req1.session_id,
            response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )
        first_result = await first
        assert first_result.status == "cancelled"

        assert hub.pending_request_count("s1") == 1

        assert hub.cancel_pending_interactions(session_id="s1")
        with contextlib.suppress(asyncio.CancelledError):
            await second

        await hub.stop()

    arun(_test())


def test_runtime_hub_tracks_session_local_config_by_session() -> None:
    async def _test() -> None:
        processed = asyncio.Event()
        processed_count = 0
        hub: SessionRegistry | None = None

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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
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


def test_runtime_hub_snapshot_reflects_runtime_state() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        release = asyncio.Event()

        root_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="work"))
        model_op = op.ChangeModelOperation(session_id="s1", model_name="model-x")
        req = _pending_request("r1", "s1")

        async def _handle(operation: op.Operation) -> None:
            if operation.id == root_op.id:
                started.set()
                await release.wait()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)

        await hub.submit(root_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        hub.apply_operation_effect(model_op)
        request_task = asyncio.create_task(hub.request_user_interaction(req))
        await asyncio.sleep(0)

        snapshot = hub.snapshot("s1")
        assert snapshot is not None
        assert snapshot.session_id == "s1"
        assert snapshot.active_root_task is not None
        assert snapshot.active_root_task.operation_id == root_op.id
        assert snapshot.active_root_task.task_id == root_op.id
        assert snapshot.child_task_count == 0
        assert snapshot.pending_request_count == 1
        assert snapshot.is_idle is False
        assert snapshot.config.model_name == "model-x"

        release.set()
        hub.mark_operation_completed(root_op.id)
        assert hub.cancel_pending_interactions(session_id="s1")
        with contextlib.suppress(asyncio.CancelledError):
            await request_task
        await asyncio.sleep(0)

        done_snapshot = hub.snapshot("s1")
        assert done_snapshot is not None
        assert done_snapshot.active_root_task is None
        assert done_snapshot.child_task_count == 0
        assert done_snapshot.pending_request_count == 0
        assert done_snapshot.is_idle is True

        await hub.stop()

    arun(_test())


def test_runtime_hub_close_session_respects_idle_state() -> None:
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

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(root_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        assert await hub.close_session("s1", force=False) is False

        release.set()
        hub.mark_operation_completed(root_op.id)
        await asyncio.sleep(0)

        assert await hub.close_session("s1", force=False) is True
        assert hub.has_session_actor("s1") is False

        await hub.stop()

    arun(_test())


def test_runtime_hub_reclaim_idle_sessions_only_reclaims_idle() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        count = 0

        s1_op = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        s2_op = op.ChangeThinkingOperation(session_id="s2", thinking=Thinking(type="enabled", budget_tokens=20))
        s2_req = _pending_request("r2", "s2")

        async def _handle(operation: op.Operation) -> None:
            nonlocal count
            count += 1
            if count == 2:
                started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(s1_op)
        await hub.submit(s2_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        request_task = asyncio.create_task(hub.request_user_interaction(s2_req))
        await asyncio.sleep(0)

        reclaimed = await hub.reclaim_idle_sessions()
        assert reclaimed == ["s1"]
        assert hub.has_session_actor("s1") is False
        assert hub.has_session_actor("s2") is True

        assert hub.cancel_pending_interactions(session_id="s2")
        with contextlib.suppress(asyncio.CancelledError):
            await request_task

        reclaimed_again = await hub.reclaim_idle_sessions()
        assert reclaimed_again == ["s2"]

        await hub.stop()

    arun(_test())


def test_runtime_hub_reclaim_idle_sessions_respects_idle_ttl() -> None:
    async def _test() -> None:
        started = asyncio.Event()

        op1 = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))

        async def _handle(_operation: op.Operation) -> None:
            started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(op1)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        # Operation is non-root and already completed by handler path.
        hub.mark_operation_completed(op1.id)

        reclaimed_too_early = await hub.reclaim_idle_sessions(idle_for_seconds=0.5)
        assert reclaimed_too_early == []
        assert hub.has_session_actor("s1") is True

        await asyncio.sleep(0.55)
        reclaimed = await hub.reclaim_idle_sessions(idle_for_seconds=0.5)
        assert reclaimed == ["s1"]

        await hub.stop()

    arun(_test())


def test_runtime_hub_request_user_interaction_roundtrip() -> None:
    async def _test() -> None:
        async def _handle(_operation: op.Operation) -> None:
            return None

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        request = _pending_request("req1", "s1")

        task = asyncio.create_task(hub.request_user_interaction(request))
        await asyncio.sleep(0)
        assert hub.pending_request_count("s1") == 1

        hub.respond_user_interaction(
            request_id="req1",
            session_id="s1",
            response=user_interaction.UserInteractionResponse(
                status="submitted",
                payload=user_interaction.AskUserQuestionResponsePayload(
                    answers=[
                        user_interaction.AskUserQuestionAnswer(
                            question_id="q1",
                            selected_option_ids=["o1"],
                        )
                    ]
                ),
            ),
        )

        response = await task
        assert response.status == "submitted"
        assert response.payload is not None
        assert response.payload.kind == "ask_user_question"
        assert response.payload.answers[0].selected_option_ids == ["o1"]
        assert hub.pending_request_count("s1") == 0

        await hub.stop()

    arun(_test())


def test_runtime_hub_respond_immediately_clears_pending_count() -> None:
    """pending_request_count must drop to 0 synchronously after respond, before yielding to the event loop."""

    async def _test() -> None:
        async def _handle(_operation: op.Operation) -> None:
            return None

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        request = _pending_request("req1", "s1")

        task = asyncio.create_task(hub.request_user_interaction(request))
        await asyncio.sleep(0)
        assert hub.pending_request_count("s1") == 1

        # respond_user_interaction must eagerly finalize: count drops without yielding.
        hub.respond_user_interaction(
            request_id="req1",
            session_id="s1",
            response=user_interaction.UserInteractionResponse(status="cancelled", payload=None),
        )
        # No await / sleep here -- count should already be 0.
        assert hub.pending_request_count("s1") == 0

        await task
        await hub.stop()

    arun(_test())


def test_runtime_hub_bind_root_task_updates_reject_active_task_id() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        reject_done = asyncio.Event()
        rejected: list[tuple[str, str | None]] = []

        first_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        second_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="second"))

        async def _handle(operation: op.Operation) -> None:
            if operation.id == first_op.id:
                started.set()

        async def _reject(operation: op.Operation, active_task_id: str | None) -> None:
            rejected.append((operation.id, active_task_id))
            reject_done.set()

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(first_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        hub.bind_root_task(operation_id=first_op.id, task_id="task-xyz")
        await hub.submit(second_op)
        await asyncio.wait_for(reject_done.wait(), timeout=1.0)

        assert rejected == [(second_op.id, "task-xyz")]

        hub.mark_operation_completed(first_op.id)
        hub.mark_operation_completed(second_op.id)
        await hub.stop()

    arun(_test())


def test_runtime_hub_runs_sessions_concurrently() -> None:
    async def _test() -> None:
        started_s1 = asyncio.Event()
        started_s2 = asyncio.Event()
        release_s1 = asyncio.Event()
        release_s2 = asyncio.Event()

        s1_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        s2_op = op.RunAgentOperation(session_id="s2", input=UserInputPayload(text="second"))

        async def _handle(operation: op.Operation) -> None:
            if operation.id == s1_op.id:
                started_s1.set()
                await release_s1.wait()
            if operation.id == s2_op.id:
                started_s2.set()
                await release_s2.wait()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(s1_op)
        await asyncio.wait_for(started_s1.wait(), timeout=1.0)

        await hub.submit(s2_op)
        await asyncio.wait_for(started_s2.wait(), timeout=0.3)

        release_s1.set()
        release_s2.set()
        hub.mark_operation_completed(s1_op.id)
        hub.mark_operation_completed(s2_op.id)
        await hub.stop()

    arun(_test())


def test_runtime_hub_child_task_state_affects_snapshot_and_idle() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        op1 = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))

        async def _handle(_operation: op.Operation) -> None:
            started.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(op1)
        await asyncio.wait_for(started.wait(), timeout=1.0)
        hub.mark_operation_completed(op1.id)

        snap_idle = hub.snapshot("s1")
        assert snap_idle is not None
        assert snap_idle.child_task_count == 0
        assert snap_idle.is_idle is True

        hub.mark_child_task_state(session_id="s1", task_id="child-1", is_active=True)
        snap_busy = hub.snapshot("s1")
        assert snap_busy is not None
        assert snap_busy.child_task_count == 1
        assert snap_busy.is_idle is False

        hub.mark_child_task_state(session_id="s1", task_id="child-1", is_active=False)
        snap_done = hub.snapshot("s1")
        assert snap_done is not None
        assert snap_done.child_task_count == 0
        assert snap_done.is_idle is True

        await hub.stop()

    arun(_test())


def test_runtime_hub_preempts_running_root_with_interrupt_control() -> None:
    async def _test() -> None:
        started = asyncio.Event()
        release = asyncio.Event()
        interrupt_seen = asyncio.Event()

        normal_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="work"))
        interrupt_op = op.InterruptOperation(session_id="s1")

        async def _handle(operation: op.Operation) -> None:
            if operation.id == normal_op.id:
                started.set()
                await release.wait()
            if operation.id == interrupt_op.id:
                interrupt_seen.set()

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        await hub.submit(normal_op)
        await asyncio.wait_for(started.wait(), timeout=1.0)

        await hub.submit(interrupt_op)
        await asyncio.wait_for(interrupt_seen.wait(), timeout=0.3)

        release.set()
        hub.mark_operation_completed(normal_op.id)
        hub.mark_operation_completed(interrupt_op.id)
        await hub.stop()

    arun(_test())


def test_runtime_hub_cancel_pending_interactions_cancels_waiter() -> None:
    async def _test() -> None:
        async def _handle(_operation: op.Operation) -> None:
            return None

        async def _reject(_operation: op.Operation, _active_root_operation_id: str | None) -> None:
            raise AssertionError("should not reject")

        hub = SessionRegistry(handle_operation=_handle, reject_operation=_reject)
        request = _pending_request("req1", "s1")

        task = asyncio.create_task(hub.request_user_interaction(request))
        await asyncio.sleep(0)

        assert hub.cancel_pending_interactions(session_id="s1") is True
        cancelled = False
        try:
            await task
        except asyncio.CancelledError:
            cancelled = True
        assert cancelled
        assert hub.pending_request_count("s1") == 0

        await hub.stop()

    arun(_test())
