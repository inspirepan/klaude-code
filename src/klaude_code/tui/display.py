from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine
from typing import Any, override

from klaude_code.app.ports import DisplayABC
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.tui.machine import DisplayStateMachine, is_cancelled_task_result
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.terminal.notifier import Notification, NotificationType, TerminalNotifier
from klaude_code.tui.terminal.title import update_terminal_title


class TUIDisplay(DisplayABC):
    """Interactive terminal display using Rich for rendering."""

    _CONTINUE_PROMPT_SUGGESTION = "/continue"

    def __init__(
        self,
        theme: str | None = None,
        notifier: TerminalNotifier | None = None,
        on_prompt_suggestion: Callable[[str | None], None] | None = None,
    ):
        self._notifier = notifier or TerminalNotifier()
        self._machine = DisplayStateMachine()
        self._renderer = TUICommandRenderer(theme=theme, notifier=self._notifier)
        self._on_prompt_suggestion = on_prompt_suggestion
        self._interrupt_prompt_suggestion_session_id: str | None = None

        self._sigint_toast_clear_handle: asyncio.Handle | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()

    def _create_bg_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @override
    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        event = envelope.event
        if isinstance(event, events.ReplayHistoryEvent):
            # Replay does not need streaming UI; disable bottom Live rendering to avoid
            # repaint overhead and flicker while reconstructing history.
            self._renderer.stop_bottom_live()
            self._renderer.set_stream_renderable(None)
            self._renderer.set_replay_mode(True)
            try:
                await self._renderer.execute(self._machine.begin_replay())
                for item in event.events:
                    log_debug(
                        f"[Replay] [{item.__class__.__name__}]",
                        item.model_dump_json(exclude_none=True),
                        debug_type=DebugType.UI_EVENT,
                    )

                    commands = self._machine.transition_replay(item)
                    if commands:
                        await self._renderer.execute(commands)
                await self._renderer.execute(self._machine.end_replay())
            finally:
                self._renderer.set_replay_mode(False)
            self._restore_prompt_suggestion_from_replay(event.events)
            return

        log_debug(
            f"[{event.__class__.__name__}]",
            event.model_dump_json(exclude_none=True),
            debug_type=DebugType.UI_EVENT,
        )
        self._handle_prompt_suggestion_event(event)
        commands = self._machine.transition(event)
        if commands:
            await self._renderer.execute(commands)

    def _set_prompt_suggestion(self, text: str | None) -> None:
        if self._on_prompt_suggestion is None:
            return
        with contextlib.suppress(Exception):
            self._on_prompt_suggestion(text)

    def _handle_prompt_suggestion_event(self, event: events.Event) -> None:
        match event:
            case events.PromptSuggestionReadyEvent() as e:
                self._interrupt_prompt_suggestion_session_id = None
                self._set_prompt_suggestion(e.text)
            case events.PromptSuggestionClearedEvent():
                self._interrupt_prompt_suggestion_session_id = None
                self._set_prompt_suggestion(None)
            case events.InterruptEvent() as e:
                self._interrupt_prompt_suggestion_session_id = e.session_id
            case events.TaskFinishEvent() as e:
                if self._interrupt_prompt_suggestion_session_id != e.session_id:
                    return
                self._interrupt_prompt_suggestion_session_id = None
                if is_cancelled_task_result(e.task_result):
                    self._set_prompt_suggestion(self._CONTINUE_PROMPT_SUGGESTION)
            case events.UserMessageEvent():
                self._interrupt_prompt_suggestion_session_id = None
            case _:
                pass

    def _restore_prompt_suggestion_from_replay(self, replay_events: list[events.ReplayEventUnion]) -> None:
        """Pre-fill the input placeholder with the last still-valid suggestion.

        A suggestion is invalidated by any later UserMessageEvent in the same
        replay stream (mirrors the live ``PromptSuggestionClearedEvent`` that
        fires on a new turn but is not persisted). Interrupted cancelled tasks
        synthesize the same ``/continue`` fallback used by live display events.
        """
        if self._on_prompt_suggestion is None:
            return
        suggestion: str | None = None
        interrupt_session_id: str | None = None
        for item in replay_events:
            if isinstance(item, events.PromptSuggestionReadyEvent):
                suggestion = item.text
                interrupt_session_id = None
            elif isinstance(item, events.UserMessageEvent):
                suggestion = None
                interrupt_session_id = None
            elif isinstance(item, events.InterruptEvent):
                suggestion = None
                interrupt_session_id = item.session_id
            elif isinstance(item, events.TaskFinishEvent) and interrupt_session_id == item.session_id:
                suggestion = self._CONTINUE_PROMPT_SUGGESTION if is_cancelled_task_result(item.task_result) else None
                interrupt_session_id = None
        if suggestion is None:
            return
        self._set_prompt_suggestion(suggestion)

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
        with contextlib.suppress(Exception):
            self._renderer.flush_open_blocks()

    def show_progress_ui(self) -> None:
        """Restore bottom status line after temporary interactive prompts."""

        with contextlib.suppress(Exception):
            self._renderer.spinner_start()

    def set_model_name(self, model_name: str | None) -> None:
        """Set model name for terminal title updates."""
        self._machine.set_model_name(model_name)
        update_terminal_title(
            model_name,
            prefix=self._machine.terminal_title_prefix,
            session_title=self._machine.session_title,
        )

    def notify_ask_user_question(self, *, question_count: int, headers: list[str] | None = None) -> None:
        if question_count <= 0:
            return
        noun = "question" if question_count == 1 else "questions"
        body = f"{question_count} {noun} waiting for your answer"
        if headers:
            body += f": {' / '.join(headers)}"
        self._notifier.notify(
            Notification(
                type=NotificationType.ASK_USER_QUESTION,
                title="Input Required",
                body=body,
            )
        )
