from __future__ import annotations

from dataclasses import dataclass

from rich.rule import Rule
from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events
from klaude_code.ui.core.stage_manager import Stage, StageManager
from klaude_code.ui.modes.repl.renderer import REPLRenderer
from klaude_code.ui.renderers.assistant import ASSISTANT_MESSAGE_MARK
from klaude_code.ui.renderers.thinking import THINKING_MESSAGE_MARK, normalize_thinking_content
from klaude_code.ui.rich import status as r_status
from klaude_code.ui.rich.markdown import MarkdownStream, ThinkingMarkdown
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.terminal.notifier import Notification, NotificationType, TerminalNotifier, emit_tmux_signal
from klaude_code.ui.terminal.progress_bar import OSC94States, emit_osc94


def extract_last_bold_header(text: str) -> str | None:
    """Extract the latest complete bold header ("**...**") from text.

    We treat a bold segment as a "header" only if it appears at the beginning
    of a line (ignoring leading whitespace). This avoids picking up incidental
    emphasis inside paragraphs.

    Returns None if no complete bold segment is available yet.
    """

    last: str | None = None
    i = 0
    while True:
        start = text.find("**", i)
        if start < 0:
            break

        line_start = text.rfind("\n", 0, start) + 1
        if text[line_start:start].strip():
            i = start + 2
            continue

        end = text.find("**", start + 2)
        if end < 0:
            break

        inner = " ".join(text[start + 2 : end].split())
        if inner and "\n" not in inner:
            last = inner

        i = end + 2

    return last


@dataclass
class ActiveStream:
    """Active streaming state containing buffer and markdown renderer.

    This represents an active streaming session where content is being
    accumulated in a buffer and rendered via MarkdownStream.
    When streaming ends, this object is replaced with None.
    """

    buffer: str
    mdstream: MarkdownStream

    def append(self, content: str) -> None:
        self.buffer += content


class StreamState:
    """Manages assistant message streaming state.

    The streaming state is either:
    - None: No active stream
    - ActiveStream: Active streaming with buffer and markdown renderer

    This design ensures buffer and mdstream are always in sync.
    """

    def __init__(self) -> None:
        self._active: ActiveStream | None = None

    @property
    def is_active(self) -> bool:
        return self._active is not None

    @property
    def buffer(self) -> str:
        return self._active.buffer if self._active else ""

    @property
    def mdstream(self) -> MarkdownStream | None:
        return self._active.mdstream if self._active else None

    def start(self, mdstream: MarkdownStream) -> None:
        """Start a new streaming session."""
        self._active = ActiveStream(buffer="", mdstream=mdstream)

    def append(self, content: str) -> None:
        """Append content to the buffer."""
        if self._active:
            self._active.append(content)

    def finish(self) -> None:
        """End the current streaming session."""
        self._active = None


class ActivityState:
    """Represents the current activity state for spinner display.

    This is a discriminated union where the state is either:
    - None (thinking/idle)
    - Composing (assistant is streaming text)
    - ToolCalls (one or more tool calls in progress)

    Composing and ToolCalls are mutually exclusive - when tool calls start,
    composing state is automatically cleared.
    """

    def __init__(self) -> None:
        self._composing: bool = False
        self._buffer_length: int = 0
        self._tool_calls: dict[str, int] = {}

    @property
    def is_composing(self) -> bool:
        return self._composing and not self._tool_calls

    @property
    def has_tool_calls(self) -> bool:
        return bool(self._tool_calls)

    def set_composing(self, composing: bool) -> None:
        self._composing = composing
        if not composing:
            self._buffer_length = 0

    def set_buffer_length(self, length: int) -> None:
        self._buffer_length = length

    def add_tool_call(self, tool_name: str) -> None:
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def clear_tool_calls(self) -> None:
        self._tool_calls = {}

    def reset(self) -> None:
        self._composing = False
        self._buffer_length = 0
        self._tool_calls = {}

    def get_activity_text(self) -> Text | None:
        """Get activity text for display. Returns None if idle/thinking."""
        if self._tool_calls:
            activity_text = Text()
            first = True
            for name, count in self._tool_calls.items():
                if not first:
                    activity_text.append(", ")
                activity_text.append(Text(name, style=ThemeKey.STATUS_TEXT_BOLD))
                if count > 1:
                    activity_text.append(f" x {count}")
                first = False
            return activity_text
        if self._composing:
            # Main status text with creative verb
            text = Text()
            text.append("Composing", style=ThemeKey.STATUS_TEXT_BOLD)
            if self._buffer_length > 0:
                text.append(f" ({self._buffer_length:,})", style=ThemeKey.STATUS_TEXT)
            return text
        return None


class SpinnerStatusState:
    """Multi-layer spinner status state management.

    Layers:
    - todo_status: Set by TodoChange (preferred when present)
    - reasoning_status: Derived from Thinking/ThinkingDelta bold headers
    - activity: Current activity (composing or tool_calls), mutually exclusive
    - context_percent: Context usage percentage, updated during task execution

    Display logic:
    - If activity: show base + activity (if base exists) or activity + "..."
    - Elif base_status: show base_status
    - Else: show "Thinking …"
    - Context percent is appended at the end if available
    """

    def __init__(self) -> None:
        self._todo_status: str | None = None
        self._reasoning_status: str | None = None
        self._activity = ActivityState()
        self._context_percent: float | None = None

    def reset(self) -> None:
        """Reset all layers."""
        self._todo_status = None
        self._reasoning_status = None
        self._activity.reset()
        self._context_percent = None

    def set_todo_status(self, status: str | None) -> None:
        """Set base status from TodoChange."""
        self._todo_status = status

    def set_reasoning_status(self, status: str | None) -> None:
        """Set reasoning-derived base status from ThinkingDelta bold headers."""
        self._reasoning_status = status

    def set_composing(self, composing: bool) -> None:
        """Set composing state when assistant is streaming."""
        if composing:
            self._reasoning_status = None
        self._activity.set_composing(composing)

    def set_buffer_length(self, length: int) -> None:
        """Set buffer length for composing state display."""
        self._activity.set_buffer_length(length)

    def add_tool_call(self, tool_name: str) -> None:
        """Add a tool call to the accumulator."""
        self._activity.add_tool_call(tool_name)

    def clear_tool_calls(self) -> None:
        """Clear tool calls."""
        self._activity.clear_tool_calls()

    def clear_for_new_turn(self) -> None:
        """Clear activity state for a new turn."""
        self._activity.reset()

    def set_context_percent(self, percent: float) -> None:
        """Set context usage percentage."""
        self._context_percent = percent

    def get_activity_text(self) -> Text | None:
        """Get current activity text. Returns None if idle."""
        return self._activity.get_activity_text()

    def get_status(self) -> Text:
        """Get current spinner status as rich Text (without context)."""
        activity_text = self._activity.get_activity_text()

        base_status = self._reasoning_status or self._todo_status

        if base_status:
            if activity_text:
                result = Text()
                result.append(base_status, style=ThemeKey.STATUS_TEXT_BOLD_ITALIC)
                result.append(" | ")
                result.append_text(activity_text)
            else:
                result = Text(base_status, style=ThemeKey.STATUS_TEXT_BOLD_ITALIC)
        elif activity_text:
            activity_text.append(" …")
            result = activity_text
        else:
            result = Text(const.STATUS_DEFAULT_TEXT, style=ThemeKey.STATUS_TEXT)

        return result

    def get_right_text(self) -> r_status.DynamicText | None:
        """Get right-aligned status text (elapsed time and optional context %)."""

        elapsed_text = r_status.current_elapsed_text()
        has_context = self._context_percent is not None

        if elapsed_text is None and not has_context:
            return None

        def _render() -> Text:
            parts: list[str] = []
            if self._context_percent is not None:
                parts.append(f"{self._context_percent:.1f}%")
            current_elapsed = r_status.current_elapsed_text()
            if current_elapsed is not None:
                if parts:
                    parts.append(" · ")
                parts.append(current_elapsed)
            return Text("".join(parts), style=ThemeKey.METADATA_DIM)

        return r_status.DynamicText(_render)


class DisplayEventHandler:
    """Handle REPL events, buffering and delegating rendering work."""

    def __init__(self, renderer: REPLRenderer, notifier: TerminalNotifier | None = None):
        self.renderer = renderer
        self.notifier = notifier
        self.assistant_stream = StreamState()
        self.thinking_stream = StreamState()
        self.spinner_status = SpinnerStatusState()

        self.stage_manager = StageManager(
            finish_assistant=self._finish_assistant_stream,
            finish_thinking=self._finish_thinking_stream,
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
            case events.ThinkingDeltaEvent() as e:
                await self._on_thinking_delta(e)
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
            case events.ContextUsageEvent() as e:
                self._on_context_usage(e)
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
        await self._flush_assistant_buffer(self.assistant_stream)
        await self._flush_thinking_buffer(self.thinking_stream)

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
        if event.sub_agent_state is None:
            r_status.set_task_start()
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
        self.spinner_status.set_reasoning_status(None)
        self._update_spinner()

    async def _on_thinking(self, event: events.ThinkingEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        # If streaming was active, finalize it
        if self.thinking_stream.is_active:
            await self._finish_thinking_stream()
        else:
            # Non-streaming path (history replay or models without delta support)
            reasoning_status = extract_last_bold_header(normalize_thinking_content(event.content))
            if reasoning_status:
                self.spinner_status.set_reasoning_status(reasoning_status)
                self._update_spinner()
            await self.stage_manager.enter_thinking_stage()
            self.renderer.display_thinking(event.content)

    async def _on_thinking_delta(self, event: events.ThinkingDeltaEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return

        first_delta = not self.thinking_stream.is_active
        if first_delta:
            mdstream = MarkdownStream(
                mdargs={
                    "code_theme": self.renderer.themes.code_theme,
                    "style": ThemeKey.THINKING,
                },
                theme=self.renderer.themes.thinking_markdown_theme,
                console=self.renderer.console,
                live_sink=self.renderer.set_stream_renderable if const.MARKDOWN_STREAM_LIVE_REPAINT_ENABLED else None,
                mark=THINKING_MESSAGE_MARK,
                mark_style=ThemeKey.THINKING,
                left_margin=const.MARKDOWN_LEFT_MARGIN,
                markdown_class=ThinkingMarkdown,
            )
            self.thinking_stream.start(mdstream)

        self.thinking_stream.append(event.content)

        reasoning_status = extract_last_bold_header(normalize_thinking_content(self.thinking_stream.buffer))
        if reasoning_status:
            self.spinner_status.set_reasoning_status(reasoning_status)
            self._update_spinner()

        if first_delta and self.thinking_stream.mdstream is not None:
            self.thinking_stream.mdstream.update(normalize_thinking_content(self.thinking_stream.buffer))

        await self.stage_manager.enter_thinking_stage()
        await self._flush_thinking_buffer(self.thinking_stream)

    async def _on_assistant_delta(self, event: events.AssistantMessageDeltaEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            self.spinner_status.set_composing(True)
            self._update_spinner()
            return
        if len(event.content.strip()) == 0 and self.stage_manager.current_stage != Stage.ASSISTANT:
            return
        first_delta = not self.assistant_stream.is_active
        if first_delta:
            self.spinner_status.set_composing(True)
            self.spinner_status.clear_tool_calls()
            self._update_spinner()
            mdstream = MarkdownStream(
                mdargs={"code_theme": self.renderer.themes.code_theme},
                theme=self.renderer.themes.markdown_theme,
                console=self.renderer.console,
                live_sink=self.renderer.set_stream_renderable if const.MARKDOWN_STREAM_LIVE_REPAINT_ENABLED else None,
                mark=ASSISTANT_MESSAGE_MARK,
                left_margin=const.MARKDOWN_LEFT_MARGIN,
            )
            self.assistant_stream.start(mdstream)
        self.assistant_stream.append(event.content)
        self.spinner_status.set_buffer_length(len(self.assistant_stream.buffer))
        if not first_delta:
            self._update_spinner()
        if first_delta and self.assistant_stream.mdstream is not None:
            self.assistant_stream.mdstream.update(self.assistant_stream.buffer)
        await self.stage_manager.transition_to(Stage.ASSISTANT)
        await self._flush_assistant_buffer(self.assistant_stream)

    async def _on_assistant_message(self, event: events.AssistantMessageEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        await self.stage_manager.transition_to(Stage.ASSISTANT)
        if self.assistant_stream.is_active:
            mdstream = self.assistant_stream.mdstream
            assert mdstream is not None
            mdstream.update(event.content.strip(), final=True)
        else:
            self.renderer.display_assistant_message(event.content)
        self.assistant_stream.finish()
        self.spinner_status.set_composing(False)
        self._update_spinner()
        await self.stage_manager.transition_to(Stage.WAITING)
        self.renderer.print()
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
        if self.renderer.is_sub_agent_session(event.session_id) and event.status == "success":
            return
        await self.stage_manager.transition_to(Stage.TOOL_RESULT)
        with self.renderer.session_print_context(event.session_id):
            self.renderer.display_tool_call_result(event)

    def _on_task_metadata(self, event: events.TaskMetadataEvent) -> None:
        self.renderer.display_task_metadata(event)

    def _on_todo_change(self, event: events.TodoChangeEvent) -> None:
        active_form_status_text = self._extract_active_form_text(event)
        self.spinner_status.set_todo_status(active_form_status_text if active_form_status_text else None)
        # Clear tool calls when todo changes, as the tool execution has advanced
        self.spinner_status.clear_for_new_turn()
        self._update_spinner()

    def _on_context_usage(self, event: events.ContextUsageEvent) -> None:
        if self.renderer.is_sub_agent_session(event.session_id):
            return
        self.spinner_status.set_context_percent(event.context_percent)
        self._update_spinner()

    async def _on_task_finish(self, event: events.TaskFinishEvent) -> None:
        self.renderer.display_task_finish(event)
        if not self.renderer.is_sub_agent_session(event.session_id):
            r_status.clear_task_start()
            emit_osc94(OSC94States.HIDDEN)
            self.spinner_status.reset()
            self.renderer.spinner_stop()
            self.renderer.console.print(Rule(characters="─", style=ThemeKey.LINES))
            emit_tmux_signal()  # Signal test harness if KLAUDE_TEST_SIGNAL is set
        await self.stage_manager.transition_to(Stage.WAITING)
        self._maybe_notify_task_finish(event)

    async def _on_interrupt(self, event: events.InterruptEvent) -> None:
        self.renderer.spinner_stop()
        self.spinner_status.reset()
        r_status.clear_task_start()
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
        r_status.clear_task_start()

    # ─────────────────────────────────────────────────────────────────────────────
    # Private helper methods
    # ─────────────────────────────────────────────────────────────────────────────

    async def _finish_assistant_stream(self) -> None:
        if self.assistant_stream.is_active:
            mdstream = self.assistant_stream.mdstream
            assert mdstream is not None
            mdstream.update(self.assistant_stream.buffer, final=True)
            self.assistant_stream.finish()

    def _update_spinner(self) -> None:
        """Update spinner text from current status state."""
        status_text = self.spinner_status.get_status()
        right_text = self.spinner_status.get_right_text()
        self.renderer.spinner_update(
            status_text,
            right_text,
        )

    async def _flush_assistant_buffer(self, state: StreamState) -> None:
        if state.is_active:
            mdstream = state.mdstream
            assert mdstream is not None
            mdstream.update(state.buffer)

    async def _flush_thinking_buffer(self, state: StreamState) -> None:
        if state.is_active:
            mdstream = state.mdstream
            assert mdstream is not None
            mdstream.update(normalize_thinking_content(state.buffer))

    async def _finish_thinking_stream(self) -> None:
        if self.thinking_stream.is_active:
            mdstream = self.thinking_stream.mdstream
            assert mdstream is not None
            mdstream.update(normalize_thinking_content(self.thinking_stream.buffer), final=True)
            self.thinking_stream.finish()
            self.renderer.print()
            self.renderer.spinner_start()

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
                if len(todo.active_form) > 0:
                    status_text = todo.active_form
                if len(todo.content) > 0:
                    status_text = todo.content
        return status_text.replace("\n", " ").strip()
