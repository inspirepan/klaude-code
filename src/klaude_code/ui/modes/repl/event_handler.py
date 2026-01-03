from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any

from klaude_code.protocol import events
from klaude_code.ui.modes.repl.renderer import REPLRenderer
from klaude_code.ui.state.command_renderer import CommandRenderer
from klaude_code.ui.state.state_machine import DisplayStateMachine
from klaude_code.ui.terminal.notifier import TerminalNotifier


class DisplayEventHandler:
    """Handle REPL events via a simplified state machine.

    Architecture:
    - `DisplayStateMachine` is pure logic: event -> RenderCommand[]
    - `CommandRenderer` executes RenderCommand[] against `REPLRenderer`

    Sub-agent sessions are supported via `session_id` routing inside the machine.
    """

    def __init__(self, renderer: REPLRenderer, notifier: TerminalNotifier | None = None):
        self._renderer = renderer
        self._notifier = notifier
        self._machine = DisplayStateMachine()
        self._executor = CommandRenderer(renderer, notifier=notifier)
        self._sigint_toast_clear_handle: asyncio.Handle | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _create_bg_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def consume_event(self, event: events.Event) -> None:
        commands = self._machine.transition(event)
        await self._executor.execute(commands)

    async def stop(self) -> None:
        if self._sigint_toast_clear_handle is not None:
            with contextlib.suppress(Exception):
                self._sigint_toast_clear_handle.cancel()
            self._sigint_toast_clear_handle = None

        for task in list(self._bg_tasks):
            with contextlib.suppress(Exception):
                task.cancel()
        self._bg_tasks.clear()

        await self._executor.stop()

    def show_sigint_exit_toast(self, *, window_seconds: float = 2.0) -> None:
        """Show a transient Ctrl+C hint in the REPL status line."""

        async def _apply_show() -> None:
            await self._executor.execute(self._machine.show_sigint_exit_toast())

        async def _apply_clear() -> None:
            await self._executor.execute(self._machine.clear_sigint_exit_toast())

        loop = asyncio.get_running_loop()
        self._create_bg_task(_apply_show())

        if self._sigint_toast_clear_handle is not None:
            with contextlib.suppress(Exception):
                self._sigint_toast_clear_handle.cancel()
            self._sigint_toast_clear_handle = None

        def _schedule_clear() -> None:
            self._create_bg_task(_apply_clear())

        self._sigint_toast_clear_handle = loop.call_later(window_seconds, _schedule_clear)
