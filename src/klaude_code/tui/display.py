from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, override

from klaude_code.app.ports import DisplayABC
from klaude_code.control.event_tape import EventTape, apply_retractions
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.input.flicker_safe_stdout import write_scrollback_bulk
from klaude_code.tui.machine import DisplayStateMachine, is_cancelled_task_result
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.terminal.notifier import Notification, NotificationType, TerminalNotifier
from klaude_code.tui.terminal.title import update_terminal_title
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail


class TUIDisplay(DisplayABC):
    """Interactive terminal display using Rich for rendering."""

    _CONTINUE_PROMPT_SUGGESTION = "/continue"

    def __init__(
        self,
        theme: str | None = None,
        notifier: TerminalNotifier | None = None,
        on_prompt_suggestion: Callable[[str | None], None] | None = None,
        on_status_update: Callable[[tuple[PromptStatusLine, ...], str | None, bool], None] | None = None,
        on_stream_update: Callable[[tuple[str, ...], bool, str], None] | None = None,
    ):
        self._notifier = notifier or TerminalNotifier()
        # One holder, shared: the machine decides which commands to emit and the
        # renderer decides how to draw them, and a mismatch paints a mixed transcript.
        self._detail = TranscriptDetail()
        self._machine = DisplayStateMachine(detail=self._detail)
        self._renderer = TUICommandRenderer(
            theme=theme,
            notifier=self._notifier,
            status_sink=on_status_update,
            stream_sink=on_stream_update,
            detail=self._detail,
        )
        self._on_prompt_suggestion = on_prompt_suggestion
        self._interrupt_prompt_suggestion_session_id: str | None = None

        self._sigint_toast_clear_handle: asyncio.Handle | None = None
        self._bg_tasks: set[asyncio.Task[None]] = set()
        # Everything the display has consumed, so a transcript rebuild (Ctrl+O
        # detail toggle, /refresh) can repaint the screen without asking the
        # runtime — including in-flight turns that are not persisted yet.
        self._tape = EventTape()

    @property
    def transcript_detail(self) -> Detail:
        return self._detail.current

    @property
    def compact_transcript(self) -> bool:
        return self._detail.is_compact

    def _create_bg_task(self, coro: Coroutine[Any, Any, None]) -> None:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    @override
    async def consume_envelope(self, envelope: events.EventEnvelope) -> None:
        event = envelope.event
        if isinstance(event, events.ReplayHistoryEvent):
            self._tape.record(event)
            # Persisted-history replay: live-turn events follow on the live
            # stream, so dangling "active" states are stale (killed sessions).
            await self._render_events_to_scrollback(event.events, clear_screen=False, drop_dangling_tasks=True)
            self._restore_prompt_suggestion_from_replay(event.events)
            return

        log_debug(
            f"[{event.__class__.__name__}]",
            lambda: event.model_dump_json(exclude_none=True),
            debug_type=DebugType.UI_EVENT,
        )
        # Display-local control events: not recorded on the tape (they describe
        # the rebuild, not the transcript) and handled inside this serialized
        # consumer so a rebuild can never interleave with a live event.
        if isinstance(event, events.ToggleTranscriptDetailEvent):
            self._detail.toggle()
            await self._render_events_to_scrollback(apply_retractions(self._tape.snapshot()), clear_screen=True)
            return
        if isinstance(event, events.RefreshDisplayEvent):
            await self._render_events_to_scrollback(apply_retractions(self._tape.snapshot()), clear_screen=True)
            return
        if isinstance(event, events.UserMessageRetractedEvent):
            # A transcript event (recorded so later rebuilds keep hiding the
            # turn), but rendered as a full repaint: the retracted turn is
            # already on screen, so erasing it needs a clear + re-render, not
            # a state-machine transition.
            self._tape.record(event)
            await self._render_events_to_scrollback(apply_retractions(self._tape.snapshot()), clear_screen=True)
            return

        self._handle_prompt_suggestion_event(event)
        if self._machine.handles(type(event)):
            self._tape.record(event)
        commands = self._machine.transition(event)
        if commands:
            await self._renderer.execute(commands)

    async def _render_events_to_scrollback(
        self, items: Sequence[events.Event], *, clear_screen: bool, drop_dangling_tasks: bool = False
    ) -> None:
        """Rebuild machine state and scrollback from `items` in one bulk paint.

        Used both to consume a ReplayHistoryEvent (append below the banner) and
        to repaint the whole screen from the tape (toggle / refresh, with
        clear). The machine re-runs every event with live semantics, so after
        the rebuild its state matches what live consumption had built — open
        streams and running sub-agents included — and subsequent live events
        continue seamlessly.
        """
        # A rebuild does not need streaming UI; disable prompt live rendering
        # while reconstructing stable scrollback history.
        self._renderer.set_stream_renderable(None)
        self._renderer.set_replay_mode(True)
        self._renderer.reset_replay_state()
        try:
            # Render the whole transcript into memory first (yielding per
            # event so the pure-CPU render loop doesn't starve the event
            # loop), then flush it in a single scrollback write. Routing
            # per-event output through the stdout proxy instead paints the
            # history as dozens of frame-sized chunks, each paying a CPR
            # round trip and a bottom-UI redraw.
            with self._renderer.bulk_render_capture() as buffer:
                await self._renderer.execute(self._machine.begin_rebuild())
                for item in items:
                    log_debug(
                        f"[Rebuild] [{item.__class__.__name__}]",
                        lambda item=item: item.model_dump_json(exclude_none=True),
                        debug_type=DebugType.UI_EVENT,
                    )

                    commands = self._machine.transition_rebuild(item)
                    if commands:
                        await self._renderer.execute(commands)
                    await asyncio.sleep(0)
                await self._renderer.execute(self._machine.end_rebuild(drop_dangling_tasks=drop_dangling_tasks))
                self._renderer.flush_rebuild_tails()
            await write_scrollback_bulk(
                buffer.getvalue(),
                clear_screen=clear_screen,
            )
        finally:
            self._renderer.set_replay_mode(False)

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
                self._interrupt_prompt_suggestion_session_id = e.session_id if e.show_notice else None
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
        fires on a new step but is not persisted). Interrupted cancelled tasks
        synthesize the same ``/continue`` fallback used by live display events
        when the task had already produced visible output.
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
                interrupt_session_id = item.session_id if item.show_notice else None
            elif isinstance(item, events.TaskFinishEvent) and interrupt_session_id == item.session_id:
                suggestion = self._CONTINUE_PROMPT_SUGGESTION if is_cancelled_task_result(item.task_result) else None
                interrupt_session_id = None
        if suggestion is None:
            return
        self._set_prompt_suggestion(suggestion)

    @override
    async def start(self) -> None:
        self._create_bg_task(self._watch_event_loop_stalls())

    @staticmethod
    async def _watch_event_loop_stalls(*, interval: float = 0.5, threshold: float = 1.0) -> None:
        """Log (after recovery) when the event loop stops running for a while.

        A stall here means something synchronous held the loop — typically a
        blocking fd-1 write into a terminal that stopped draining the pty.
        The log line lands once the loop resumes, giving forensics for
        'display frozen but session kept running' reports.
        """

        loop = asyncio.get_running_loop()
        last = loop.time()
        while True:
            await asyncio.sleep(interval)
            now = loop.time()
            gap = now - last - interval
            if gap > threshold:
                log_debug(
                    f"[watchdog] event loop stalled for {gap:.1f}s",
                    debug_type=DebugType.EXECUTION,
                )
            last = now

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

    def hide_progress_ui(self, *, flush_open_blocks: bool = True) -> None:
        """Stop transient Rich UI elements before prompt-toolkit takes control."""

        with contextlib.suppress(Exception):
            self._renderer.spinner_stop()
        if flush_open_blocks:
            with contextlib.suppress(Exception):
                self._renderer.flush_open_blocks(scoped=False)

    def show_progress_ui(self) -> None:
        """Restore bottom status line after temporary interactive prompts."""

        with contextlib.suppress(Exception):
            self._renderer.spinner_start()

    def set_progress_ui_suspended(self, suspended: bool) -> None:
        """Prevent Rich Live progress UI from repainting while prompt-toolkit owns input."""

        with contextlib.suppress(Exception):
            self._renderer.set_progress_ui_suspended(suspended)

    def refresh_prompt_status(self) -> None:
        """Refresh the prompt-toolkit status snapshot from the current Rich status state."""

        with contextlib.suppress(Exception):
            self._renderer.refresh_prompt_status()

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
