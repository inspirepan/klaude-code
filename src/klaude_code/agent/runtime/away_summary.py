"""Coordinator for the auto-triggered 'while you were away' recap.

The recap is auto-triggered only when all of the following are true:

- A task/turn finished.
- The TUI is back at the prompt.
- The user has not pressed any keys since that task finished.
- The prompt stayed idle for the configured delay.

This intentionally avoids terminal focus tracking. DECSET 1004 focus events can
cause frequent prompt_toolkit invalidations in some terminals/multiplexers,
which shows up as visible cursor flicker.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Protocol

from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import op

DEFAULT_IDLE_DELAY_SECONDS = 120


class AwaySummaryRuntime(Protocol):
    def current_session_id(self) -> str | None: ...

    def has_running_tasks(self) -> bool: ...

    async def submit(self, operation: op.Operation) -> str: ...


class AwaySummaryCoordinator:
    def __init__(
        self,
        *,
        runtime: AwaySummaryRuntime,
        idle_delay_seconds: float = DEFAULT_IDLE_DELAY_SECONDS,
    ) -> None:
        self._runtime = runtime
        self._idle_delay_seconds = idle_delay_seconds

        self._cancel_task: asyncio.Task[None] | None = None
        self._timer_task: asyncio.Task[None] | None = None
        self._eligible: bool = False
        self._prompt_active: bool = False
        self._started: bool = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        self._started = False
        self._eligible = False
        self._prompt_active = False
        await self._cancel_cancel_task()
        await self._cancel_timer()

    def notify_task_finished(self) -> None:
        if not self._started:
            return
        self._eligible = True
        if self._prompt_active:
            self._arm_timer()

    def notify_prompt_started(self) -> None:
        if not self._started:
            return
        self._prompt_active = True
        if self._eligible:
            self._arm_timer()

    def notify_prompt_ended(self) -> None:
        if not self._started:
            return
        self._prompt_active = False
        self._schedule_cancel_timer()

    def notify_user_activity(self) -> None:
        if not self._started or not self._prompt_active or not self._eligible:
            return
        self._eligible = False
        self._schedule_cancel_timer()

    def _schedule_cancel_timer(self) -> None:
        if self._cancel_task is not None and not self._cancel_task.done():
            self._cancel_task.cancel()
        self._cancel_task = asyncio.create_task(self._cancel_timer())

    async def _cancel_cancel_task(self) -> None:
        task = self._cancel_task
        self._cancel_task = None
        if task is None or task.done() or task is asyncio.current_task():
            return
        task.cancel()
        with contextlib.suppress(BaseException):
            await task

    def _arm_timer(self) -> None:
        if not self._prompt_active or not self._eligible:
            return
        if self._timer_task is not None and not self._timer_task.done():
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._idle_timer())

    async def _cancel_timer(self) -> None:
        task = self._timer_task
        self._timer_task = None
        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(BaseException):
            await task

    async def _idle_timer(self) -> None:
        try:
            await asyncio.sleep(self._idle_delay_seconds)
        except asyncio.CancelledError:
            return

        if self._timer_task is asyncio.current_task():
            self._timer_task = None

        if not self._prompt_active or not self._eligible:
            return

        if self._runtime.has_running_tasks():
            log_debug("[AwaySummary] task in progress; skip idle submit", debug_type=DebugType.EXECUTION)
            return

        await self._submit_operation()

    # ---------------------------------------------------------------------
    # Submit
    # ---------------------------------------------------------------------

    async def _submit_operation(self) -> None:
        session_id = self._runtime.current_session_id()
        if session_id is None:
            return
        self._eligible = False
        try:
            await self._runtime.submit(
                op.GenerateAwaySummaryOperation(session_id=session_id, source="auto"),
            )
        except Exception as exc:
            log_debug(f"[AwaySummary] submit failed: {exc}", debug_type=DebugType.EXECUTION)
