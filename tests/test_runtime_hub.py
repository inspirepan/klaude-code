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

        async def _handle(submission: op.Submission) -> None:
            sid = getattr(submission.operation, "session_id", None)
            handled.append((sid, submission.id))
            if len(handled) >= 3:
                done.set()

        async def _reject(_submission: op.Submission, _active_root_submission_id: str | None) -> None:
            raise AssertionError("should not reject when session is idle")

        hub = RuntimeHub(handle_submission=_handle, reject_submission=_reject)
        s1_first = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=10))
        s2_only = op.ChangeThinkingOperation(session_id="s2", thinking=Thinking(type="enabled", budget_tokens=20))
        s1_second = op.ChangeThinkingOperation(session_id="s1", thinking=Thinking(type="enabled", budget_tokens=30))

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

        async def _reject(_submission: op.Submission, _active_root_submission_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = RuntimeHub(handle_submission=_handle, reject_submission=_reject)
        operation = op.InterruptOperation(target_session_id=None)

        await hub.submit(op.Submission(id=operation.id, operation=operation))
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

        async def _handle(submission: op.Submission) -> None:
            handled.append(submission.id)

        async def _reject(submission: op.Submission, active_root_submission_id: str | None) -> None:
            rejected.append((submission.id, active_root_submission_id))
            second_rejected.set()

        hub = RuntimeHub(handle_submission=_handle, reject_submission=_reject)

        await hub.submit(op.Submission(id=first_op.id, operation=first_op))
        await hub.submit(op.Submission(id=second_op.id, operation=second_op))
        await asyncio.wait_for(second_rejected.wait(), timeout=1.0)

        hub.mark_submission_completed(first_op.id)
        hub.mark_submission_completed(second_op.id)
        await hub.stop()

        assert handled == [first_op.id]
        assert rejected == [(second_op.id, first_op.id)]

    arun(_test())


def test_runtime_hub_allows_interrupt_while_root_is_active() -> None:
    async def _test() -> None:
        handled: list[str] = []
        done = asyncio.Event()

        first_op = op.RunAgentOperation(session_id="s1", input=UserInputPayload(text="first"))
        interrupt_op = op.InterruptOperation(target_session_id="s1")

        async def _handle(submission: op.Submission) -> None:
            handled.append(submission.id)
            if submission.id == interrupt_op.id:
                done.set()

        async def _reject(_submission: op.Submission, _active_root_submission_id: str | None) -> None:
            raise AssertionError("interrupt should not be rejected")

        hub = RuntimeHub(handle_submission=_handle, reject_submission=_reject)

        await hub.submit(op.Submission(id=first_op.id, operation=first_op))
        await hub.submit(op.Submission(id=interrupt_op.id, operation=interrupt_op))
        await asyncio.wait_for(done.wait(), timeout=1.0)

        hub.mark_submission_completed(first_op.id)
        hub.mark_submission_completed(interrupt_op.id)
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

        async def _handle(submission: op.Submission) -> None:
            if hub is None:
                raise AssertionError("hub should be initialized")
            handled.append(submission.id)
            hub.mark_submission_completed(submission.id)
            if len(handled) == 2:
                done.set()

        async def _reject(_submission: op.Submission, _active_root_submission_id: str | None) -> None:
            raise AssertionError("second root should be accepted after completion")

        hub = RuntimeHub(handle_submission=_handle, reject_submission=_reject)

        await hub.submit(op.Submission(id=first_op.id, operation=first_op))
        await hub.submit(op.Submission(id=second_op.id, operation=second_op))

        await asyncio.wait_for(done.wait(), timeout=1.0)
        await hub.stop()

        assert handled == [first_op.id, second_op.id]

    arun(_test())
