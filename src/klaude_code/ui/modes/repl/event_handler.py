from __future__ import annotations

from typing import Awaitable, Callable

from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events
from klaude_code.ui.core.stage_manager import Stage, StageManager
from klaude_code.ui.modes.repl.renderer import REPLRenderer
from klaude_code.ui.rich.markdown import MarkdownStream
from klaude_code.ui.terminal.notifier import Notification, NotificationType, TerminalNotifier
from klaude_code.ui.terminal.progress_bar import OSC94States, emit_osc94
from klaude_code.ui.utils.debouncer import Debouncer


class StreamState:
    def __init__(self, interval: float, flush_handler: Callable[["StreamState"], Awaitable[None]]):
        self.buffer: str = ""
        self.mdstream: MarkdownStream | None = None
        self._flush_handler = flush_handler
        self.debouncer = Debouncer(interval=interval, callback=self._debounced_flush)

    async def _debounced_flush(self) -> None:
        await self._flush_handler(self)

    def append(self, content: str) -> None:
        self.buffer += content

    def clear(self) -> None:
        self.buffer = ""


class SpinnerStatusState:
    """Multi-layer spinner status state management.

    Layers (from low to high priority):
    - base_status: Set by TodoChange, persistent within a turn
    - composing: True when assistant is streaming text
    - tool_calls: Accumulated from ToolCallStart, cleared at turn start

    Display logic:
    - If tool_calls: show base + tool_calls (composing is hidden)
    - Elif composing: show base + "Composing"
    - Elif base_status: show base_status
    - Else: show "Thinking …"
    """

    DEFAULT_STATUS = "Thinking …"

    def __init__(self) -> None:
        self._base_status: str | None = None
        self._composing: bool = False
        self._tool_calls: dict[str, int] = {}

    def reset(self) -> None:
        """Reset all layers."""
        self._base_status = None
        self._composing = False
        self._tool_calls = {}

    def set_base_status(self, status: str | None) -> None:
        """Set base status from TodoChange."""
        self._base_status = status

    def set_composing(self, composing: bool) -> None:
        """Set composing state when assistant is streaming."""
        self._composing = composing

    def add_tool_call(self, tool_name: str) -> None:
        """Add a tool call to the accumulator."""
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def clear_tool_calls(self) -> None:
        """Clear tool calls and composing state."""
        self._tool_calls = {}

    def clear_for_new_turn(self) -> None:
        """Clear tool calls and composing state for a new turn."""
        self._tool_calls = {}
        self._composing = False

    def get_status(self) -> Text:
        """Get current spinner status as rich Text."""
        # Build activity text (tool_calls or composing)
        activity_text: Text | None = None
        if self._tool_calls:
            activity_text = Text()
            first = True
            for name, count in self._tool_calls.items():
                if not first:
                    activity_text.append(", ")
                activity_text.append(name, style="bold")
                if count > 1:
                    activity_text.append(f" × {count}")
                first = False
        elif self._composing:
            activity_text = Text("Composing")

        if self._base_status:
            result = Text(self._base_status)
            if activity_text:
                result.append(" | ")
                result.append_text(activity_text)
            return result
        if activity_text:
            activity_text.append(" …")
            return activity_text
        return Text(self.DEFAULT_STATUS)


class DisplayEventHandler:
    """Handle REPL events, buffering and delegating rendering work."""

    def __init__(self, renderer: REPLRenderer, notifier: TerminalNotifier | None = None):
        self.renderer = renderer
        self.notifier = notifier
        self.assistant_stream = StreamState(
            interval=1 / const.UI_REFRESH_RATE_FPS, flush_handler=self._flush_assistant_buffer
        )
        self.spinner_status = SpinnerStatusState()

        self.stage_manager = StageManager(
            finish_assistant=self._finish_assistant_stream,
            on_enter_thinking=self._print_thinking_prefix,
        )

    async def consume_event(self, event: events.Event) -> None:
        match event:
            case events.ReplayHistoryEvent() as e:
                await self._on_replay_history(e)
            case events.WelcomeEvent() as e:
                self._on_welcome(e)
            case events.UserMessageEvent() as e:
                self._on_user_message(e)
            case events.TaskStartEvent() as e:
                self._on_task_start(e)
            case events.DeveloperMessageEvent() as e:
                self._on_developer_message(e)
            case events.TurnStartEvent() as e:
                self._on_turn_start(e)
            case events.ThinkingEvent() as e:
                await self._on_thinking(e)
            case events.AssistantMessageDeltaEvent() as e:
                await self._on_assistant_delta(e)
            case events.AssistantMessageEvent() as e:
                await self._on_assistant_message(e)
            case events.TurnToolCallStartEvent() as e:
                self._on_tool_call_start(e)
            case events.ToolCallEvent() as e:
                await self._on_tool_call(e)
            case events.ToolResultEvent() as e:
                await self._on_tool_result(e)
            case events.TaskMetadataEvent() as e:
                self._on_task_metadata(e)
            case events.TodoChangeEvent() as e:
                self._on_todo_change(e)
            case events.TurnEndEvent():
                pass
            case events.ResponseMetadataEvent():
                pass  # Internal event, not displayed
            case events.TaskFinishEvent() as e:
                await self._on_task_finish(e)
            case events.InterruptEvent() as e:
                await self._on_interrupt(e)
            case events.ErrorEvent() as e:
                await self._on_error(e)
            case events.EndEvent() as e:
                await self._on_end(e)

    async def stop(self) -> None:
        await self.assistant_stream.debouncer.flush()
        self.assistant_stream.debouncer.cancel()

    # ─────────────────────────────────────────────────────────────────────────────
    # Private event handlers
    # ─────────────────────────────────────────────────────────────────────────────

    async def _on_replay_history(self, event: events.ReplayHistoryEvent) -> None:
        await self.renderer.replay_history(event)
        self.renderer.spinner_stop()

    def _on_welcome(self, event: events.WelcomeEvent) -> None:
        self.renderer.display_welcome(event)

    def _on_user_message(self, event: events.UserMessageEvent) -> None:
        self.renderer.display_user_message(event)

    def _on_task_start(self, event: events.TaskStartEvent) -> None:
        self.renderer.spinner_start()
        self.renderer.display_task_start(event)
        emit_osc94(OSC94States.INDETERMINATE)

    def _on_developer_message(self, event: events.DeveloperMessageEvent) -> None:
        self.renderer.display_developer_message(event)
        self.renderer.display_command_output(event)

    def _on_turn_start(self, event: events.TurnStartEvent) -> None:
        emit_osc94(OSC94States.INDETERMINATE)
        self.renderer.display_turn_start(event)
        self.spinner_status.clear_for_new_turn()
        self._update_spinner()

    async def _on_thinking(self, event: events.ThinkingEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        await self.stage_manager.enter_thinking_stage()
        self.renderer.display_thinking(event.content)

    async def _on_assistant_delta(self, event: events.AssistantMessageDeltaEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            self.spinner_status.set_composing(True)
            self._update_spinner()
            return
        if len(event.content.strip()) == 0 and self.stage_manager.current_stage != Stage.ASSISTANT:
            return
        first_delta = self.assistant_stream.mdstream is None
        if first_delta:
            self.spinner_status.set_composing(True)
            self.spinner_status.clear_tool_calls()
            self._update_spinner()
            self.assistant_stream.mdstream = MarkdownStream(
                mdargs={"code_theme": self.renderer.themes.code_theme},
                theme=self.renderer.themes.markdown_theme,
                console=self.renderer.console,
                spinner=self.renderer.spinner_renderable(),
                mark="➤",
                indent=2,
            )
        self.assistant_stream.append(event.content)
        if first_delta and self.assistant_stream.mdstream is not None:
            # Stop spinner and immediately start MarkdownStream's Live
            # to avoid flicker. The update() call starts the Live with
            # the spinner embedded, providing seamless transition.
            self.renderer.spinner_stop()
            self.assistant_stream.mdstream.update(self.assistant_stream.buffer)
        await self.stage_manager.transition_to(Stage.ASSISTANT)
        self.assistant_stream.debouncer.schedule()

    async def _on_assistant_message(self, event: events.AssistantMessageEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        await self.stage_manager.transition_to(Stage.ASSISTANT)
        if self.assistant_stream.mdstream is not None:
            self.assistant_stream.debouncer.cancel()
            self.assistant_stream.mdstream.update(event.content.strip(), final=True)
        else:
            self.renderer.display_assistant_message(event.content)
        self.assistant_stream.clear()
        self.assistant_stream.mdstream = None
        self.spinner_status.set_composing(False)
        self._update_spinner()
        await self.stage_manager.transition_to(Stage.WAITING)
        self.renderer.spinner_start()

    def _on_tool_call_start(self, event: events.TurnToolCallStartEvent) -> None:
        from klaude_code.ui.renderers.tools import get_tool_active_form

        self.spinner_status.set_composing(False)
        self.spinner_status.add_tool_call(get_tool_active_form(event.tool_name))
        self._update_spinner()

    async def _on_tool_call(self, event: events.ToolCallEvent) -> None:
        await self.stage_manager.transition_to(Stage.TOOL_CALL)
        with self.renderer.session_print_context(event.session_id):
            self.renderer.display_tool_call(event)

    async def _on_tool_result(self, event: events.ToolResultEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        await self.stage_manager.transition_to(Stage.TOOL_RESULT)
        self.renderer.display_tool_call_result(event)

    def _on_task_metadata(self, event: events.TaskMetadataEvent) -> None:
        self.renderer.display_task_metadata(event)

    def _on_todo_change(self, event: events.TodoChangeEvent) -> None:
        active_form_status_text = self._extract_active_form_text(event)
        self.spinner_status.set_base_status(active_form_status_text if active_form_status_text else None)
        # Clear tool calls when todo changes, as the tool execution has advanced
        self.spinner_status.clear_for_new_turn()
        self._update_spinner()

    async def _on_task_finish(self, event: events.TaskFinishEvent) -> None:
        self.renderer.display_task_finish(event)
        if not self.renderer.is_sub_agent_session(event.session_id):
            emit_osc94(OSC94States.HIDDEN)
            self.spinner_status.reset()
            self.renderer.spinner_stop()
        await self.stage_manager.transition_to(Stage.WAITING)
        self._maybe_notify_task_finish(event)

    async def _on_interrupt(self, event: events.InterruptEvent) -> None:
        self.renderer.spinner_stop()
        self.spinner_status.reset()
        await self.stage_manager.transition_to(Stage.WAITING)
        emit_osc94(OSC94States.HIDDEN)
        self.renderer.display_interrupt()

    async def _on_error(self, event: events.ErrorEvent) -> None:
        emit_osc94(OSC94States.ERROR)
        await self.stage_manager.transition_to(Stage.WAITING)
        self.renderer.display_error(event)
        if not event.can_retry:
            self.renderer.spinner_stop()
            self.spinner_status.reset()

    async def _on_end(self, event: events.EndEvent) -> None:
        emit_osc94(OSC94States.HIDDEN)
        await self.stage_manager.transition_to(Stage.WAITING)
        self.renderer.spinner_stop()
        self.spinner_status.reset()

    # ─────────────────────────────────────────────────────────────────────────────
    # Private helper methods
    # ─────────────────────────────────────────────────────────────────────────────

    async def _finish_assistant_stream(self) -> None:
        if self.assistant_stream.mdstream is not None:
            self.assistant_stream.debouncer.cancel()
            self.assistant_stream.mdstream.update(self.assistant_stream.buffer, final=True)
            self.assistant_stream.mdstream = None
            self.assistant_stream.clear()

    def _print_thinking_prefix(self) -> None:
        self.renderer.display_thinking_prefix()

    def _update_spinner(self) -> None:
        """Update spinner text from current status state."""
        self.renderer.spinner_update(self.spinner_status.get_status())

    async def _flush_assistant_buffer(self, state: StreamState) -> None:
        if state.mdstream is not None:
            state.mdstream.update(state.buffer)

    def _maybe_notify_task_finish(self, event: events.TaskFinishEvent) -> None:
        if self.notifier is None:
            return
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        notification = self._build_task_finish_notification(event)
        self.notifier.notify(notification)

    def _build_task_finish_notification(self, event: events.TaskFinishEvent) -> Notification:
        body = self._compact_result_text(event.task_result)
        return Notification(
            type=NotificationType.AGENT_TASK_COMPLETE,
            title="Task Completed",
            body=body,
        )

    def _compact_result_text(self, text: str) -> str | None:
        stripped = text.strip()
        if len(stripped) == 0:
            return None
        squashed = " ".join(stripped.split())
        if len(squashed) > 200:
            return squashed[:197] + "…"
        return squashed

    def _extract_active_form_text(self, todo_event: events.TodoChangeEvent) -> str:
        status_text = ""
        for todo in todo_event.todos:
            if todo.status == "in_progress":
                if len(todo.activeForm) > 0:
                    status_text = todo.activeForm
                if len(todo.content) > 0:
                    status_text = todo.content
        return status_text.replace("\n", "")
