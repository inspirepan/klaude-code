from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from klaude_code.agent.runtime_agent_ops import _has_summary_since_last_user_turn  # pyright: ignore[reportPrivateUsage]
from klaude_code.agent.runtime_away_summary import AwaySummaryCoordinator
from klaude_code.protocol import events, message, op
from klaude_code.session.session import Session


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


class _FakeRuntime:
    def __init__(self, *, has_running: bool = False, session_id: str | None = "s1") -> None:
        self._has_running = has_running
        self._session_id = session_id
        self.submitted: list[op.Operation] = []

    def current_session_id(self) -> str | None:
        return self._session_id

    def has_running_tasks(self) -> bool:
        return self._has_running

    async def submit(self, operation: op.Operation) -> str:
        self.submitted.append(operation)
        return operation.id


async def _flush(loop_cycles: int = 5) -> None:
    for _ in range(loop_cycles):
        await asyncio.sleep(0)


def test_task_finish_then_prompt_idle_submits_operation() -> None:
    async def _body() -> _FakeRuntime:
        runtime = _FakeRuntime()
        coord = AwaySummaryCoordinator(runtime=runtime, idle_delay_seconds=0.02)  # type: ignore[arg-type]
        await coord.start()
        try:
            coord.notify_task_finished()
            coord.notify_prompt_started()
            await asyncio.sleep(0.05)
            await _flush()
        finally:
            await coord.stop()
        return runtime

    runtime = arun(_body())
    assert len(runtime.submitted) == 1
    assert isinstance(runtime.submitted[0], op.GenerateAwaySummaryOperation)
    assert runtime.submitted[0].source == "auto"
    assert runtime.submitted[0].session_id == "s1"


def test_user_activity_cancels_idle_submit() -> None:
    async def _body() -> _FakeRuntime:
        runtime = _FakeRuntime()
        coord = AwaySummaryCoordinator(runtime=runtime, idle_delay_seconds=0.05)  # type: ignore[arg-type]
        await coord.start()
        try:
            coord.notify_task_finished()
            coord.notify_prompt_started()
            await asyncio.sleep(0.01)
            coord.notify_user_activity()
            await asyncio.sleep(0.08)
            await _flush()
        finally:
            await coord.stop()
        return runtime

    runtime = arun(_body())
    assert runtime.submitted == []


def test_prompt_end_cancels_idle_submit() -> None:
    async def _body() -> _FakeRuntime:
        runtime = _FakeRuntime()
        coord = AwaySummaryCoordinator(runtime=runtime, idle_delay_seconds=0.02)  # type: ignore[arg-type]
        await coord.start()
        try:
            coord.notify_task_finished()
            coord.notify_prompt_started()
            await asyncio.sleep(0.005)
            coord.notify_prompt_ended()
            await asyncio.sleep(0.05)
            await _flush()
        finally:
            await coord.stop()
        return runtime

    runtime = arun(_body())
    assert runtime.submitted == []


def test_prompt_idle_requires_completed_task() -> None:
    async def _body() -> _FakeRuntime:
        runtime = _FakeRuntime()
        coord = AwaySummaryCoordinator(runtime=runtime, idle_delay_seconds=0.02)  # type: ignore[arg-type]
        await coord.start()
        try:
            coord.notify_prompt_started()
            await asyncio.sleep(0.05)
        finally:
            await coord.stop()
        return runtime

    runtime = arun(_body())
    assert runtime.submitted == []


def test_running_task_skips_idle_submit() -> None:
    async def _body() -> _FakeRuntime:
        runtime = _FakeRuntime(has_running=True)
        coord = AwaySummaryCoordinator(runtime=runtime, idle_delay_seconds=0.02)  # type: ignore[arg-type]
        await coord.start()
        try:
            coord.notify_task_finished()
            coord.notify_prompt_started()
            await asyncio.sleep(0.05)
            await _flush()
        finally:
            await coord.stop()
        return runtime

    runtime = arun(_body())
    assert runtime.submitted == []


# ---------------------------------------------------------------------------
# Persistence / dedup / replay behavior (handler-layer contract)
# ---------------------------------------------------------------------------


def _seed_session(items: list[message.HistoryEvent]) -> Session:
    """Build a session with pre-populated history, skipping the flush path
    which requires a running event loop. Tests only need in-memory state."""
    session = Session.create(work_dir=Path("/tmp"))
    session.conversation_history.extend(items)
    return session


def test_has_summary_since_last_user_turn_basic() -> None:
    session = _seed_session([])
    assert not _has_summary_since_last_user_turn(session)

    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("hi")))
    assert not _has_summary_since_last_user_turn(session)

    session.conversation_history.append(message.AwaySummaryEntry(text="recap 1"))
    assert _has_summary_since_last_user_turn(session)

    # New user turn resets the dedup state.
    session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("next")))
    assert not _has_summary_since_last_user_turn(session)


def test_has_summary_ignores_bash_mode_user() -> None:
    session = _seed_session(
        [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AwaySummaryEntry(text="recap"),
            # bash_mode UserMessage does not count as a real user turn.
            message.UserMessage(parts=message.text_parts_from_str("!ls"), source="bash_mode"),
        ]
    )
    assert _has_summary_since_last_user_turn(session)


def test_away_summary_entry_replays_as_event() -> None:
    session = _seed_session(
        [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AssistantMessage(parts=message.text_parts_from_str("ok")),
            message.AwaySummaryEntry(text="Debugging foo. Next: bar."),
        ]
    )
    replay = list(session.get_history_item())
    recaps = [e for e in replay if isinstance(e, events.AwaySummaryEvent)]
    assert len(recaps) == 1
    assert recaps[0].text == "Debugging foo. Next: bar."

    finish_index = next(i for i, event in enumerate(replay) if isinstance(event, events.TaskFinishEvent))
    recap_index = next(i for i, event in enumerate(replay) if isinstance(event, events.AwaySummaryEvent))
    assert finish_index < recap_index


def test_away_summary_filtered_from_llm_input() -> None:
    """AwaySummaryEntry must not leak into LLM turn input — it's not a Message."""
    session = _seed_session(
        [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AwaySummaryEntry(text="recap"),
            message.UserMessage(parts=message.text_parts_from_str("next")),
        ]
    )
    # turn.py filters get_llm_history() to (UserMessage, AssistantMessage, ToolResultMessage).
    message_types = (message.UserMessage, message.AssistantMessage, message.ToolResultMessage)
    filtered = [it for it in session.get_llm_history() if isinstance(it, message_types)]
    assert all(not isinstance(it, message.AwaySummaryEntry) for it in filtered)
    assert len(filtered) == 2  # two user messages only
