from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Coroutine
from typing import Any, override

from klaude_code.protocol import events
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.terminal.notifier import TerminalNotifier
from klaude_code.ui.core.display import DisplayABC


class TUIDisplay(DisplayABC):
    """Interactive terminal display using Rich for rendering."""

    def __init__(self, theme: str | None = None, notifier: TerminalNotifier | None = None):
        self._notifier = notifier or TerminalNotifier()
        self._machine = DisplayStateMachine()
        self._renderer = TUICommandRenderer(theme=theme, notifier=self._notifier)

        self._sigint_toast_clear_handle: asyncio.Handle | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _create_bg_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @override
    async def consume_event(self, event: events.Event) -> None:
        if isinstance(event, events.ReplayHistoryEvent):
            # Replay does not need streaming UI; disable bottom Live rendering to avoid
            # repaint overhead and flicker while reconstructing history.
            self._renderer.stop_bottom_live()
            self._renderer.set_stream_renderable(None)
            self._renderer.set_replay_mode(True)
            try:
                await self._renderer.execute(self._machine.begin_replay())
                for item in event.events:
                    commands = self._machine.transition_replay(item)
                    if commands:
                        await self._renderer.execute(commands)
                await self._renderer.execute(self._machine.end_replay())
            finally:
                self._renderer.set_replay_mode(False)
            return

        commands = self._machine.transition(event)
        if commands:
            await self._renderer.execute(commands)

    @override
    async def start(self) -> None:
        pass

    @override
    async def stop(self) -> None:
        if self._sigint_toast_clear_handle is not None:
            with contextlib.suppress(Exception):
                self._sigint_toast_clear_handle.cancel()
            self._sigint_toast_clear_handle = None

        for task in list(self._bg_tasks):
            with contextlib.suppress(Exception):
                task.cancel()
        self._bg_tasks.clear()

        await self._renderer.stop()

        with contextlib.suppress(Exception):
            self._renderer.stop_bottom_live()

    def show_sigint_exit_toast(self, *, window_seconds: float = 2.0) -> None:
        """Show a transient Ctrl+C hint in the TUI status line."""

        async def _apply_show() -> None:
            await self._renderer.execute(self._machine.show_sigint_exit_toast())

        async def _apply_clear() -> None:
            await self._renderer.execute(self._machine.clear_sigint_exit_toast())

        loop = asyncio.get_running_loop()
        self._create_bg_task(_apply_show())

        if self._sigint_toast_clear_handle is not None:
            with contextlib.suppress(Exception):
                self._sigint_toast_clear_handle.cancel()
            self._sigint_toast_clear_handle = None

        def _schedule_clear() -> None:
            self._create_bg_task(_apply_clear())

        self._sigint_toast_clear_handle = loop.call_later(window_seconds, _schedule_clear)

    def hide_progress_ui(self) -> None:
        """Stop transient Rich UI elements before prompt-toolkit takes control."""

        with contextlib.suppress(Exception):
            self._renderer.spinner_stop()
        with contextlib.suppress(Exception):
            self._renderer.stop_bottom_live()