from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import Style, StyleType
from rich.text import Text

from klaude_code.const import (
    MARKDOWN_LEFT_MARGIN,
    MARKDOWN_STREAM_LIVE_REPAINT_ENABLED,
    STATUS_DEFAULT_TEXT,
    STREAM_MAX_HEIGHT_SHRINK_RESET_LINES,
)
from klaude_code.protocol import events, model, tools
from klaude_code.tui.commands import (
    AppendAssistant,
    AppendThinking,
    EmitOsc94Error,
    EmitTmuxSignal,
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    PrintRuleLine,
    RenderAssistantImage,
    RenderCommand,
    RenderCommandOutput,
    RenderDeveloperMessage,
    RenderError,
    RenderInterrupt,
    RenderReplayHistory,
    RenderTaskFinish,
    RenderTaskMetadata,
    RenderTaskStart,
    RenderThinkingHeader,
    RenderToolCall,
    RenderToolResult,
    RenderTurnStart,
    RenderUserMessage,
    RenderWelcome,
    SpinnerStart,
    SpinnerStop,
    SpinnerUpdate,
    StartAssistantStream,
    StartThinkingStream,
    TaskClockClear,
    TaskClockStart,
)
from klaude_code.tui.components import assistant as c_assistant
from klaude_code.tui.components import command_output as c_command_output
from klaude_code.tui.components import developer as c_developer
from klaude_code.tui.components import errors as c_errors
from klaude_code.tui.components import mermaid_viewer as c_mermaid_viewer
from klaude_code.tui.components import metadata as c_metadata
from klaude_code.tui.components import sub_agent as c_sub_agent
from klaude_code.tui.components import thinking as c_thinking
from klaude_code.tui.components import tools as c_tools
from klaude_code.tui.components import user_input as c_user_input
from klaude_code.tui.components import welcome as c_welcome
from klaude_code.tui.components.common import truncate_head
from klaude_code.tui.components.rich import status as r_status
from klaude_code.tui.components.rich.live import CropAboveLive, SingleLine
from klaude_code.tui.components.rich.markdown import MarkdownStream, ThinkingMarkdown
from klaude_code.tui.components.rich.quote import Quote
from klaude_code.tui.components.rich.status import BreathingSpinner, ShimmerStatusText
from klaude_code.tui.components.rich.theme import ThemeKey, get_theme
from klaude_code.tui.terminal.image import print_kitty_image
from klaude_code.tui.terminal.notifier import (
    Notification,
    NotificationType,
    TerminalNotifier,
    emit_tmux_signal,
)
from klaude_code.tui.terminal.progress_bar import OSC94States, emit_osc94


@dataclass
class _ActiveStream:
    buffer: str
    mdstream: MarkdownStream

    def append(self, content: str) -> None:
        self.buffer += content


class _StreamState:
    def __init__(self) -> None:
        self._active: _ActiveStream | None = None

    @property
    def is_active(self) -> bool:
        return self._active is not None

    @property
    def buffer(self) -> str:
        return self._active.buffer if self._active else ""

    def start(self, mdstream: MarkdownStream) -> None:
        self._active = _ActiveStream(buffer="", mdstream=mdstream)

    def append(self, content: str) -> None:
        if self._active is None:
            return
        self._active.append(content)

    def render(self, *, transform: Callable[[str], str] | None = None, final: bool = False) -> bool:
        if self._active is None:
            return False
        text = self._active.buffer
        if transform is not None:
            text = transform(text)
        self._active.mdstream.update(text, final=final)
        if final:
            self._active = None
        return True

    def finalize(self, *, transform: Callable[[str], str] | None = None) -> bool:
        return self.render(transform=transform, final=True)


@dataclass
class _SessionStatus:
    color: Style | None = None
    color_index: int | None = None
    sub_agent_state: model.SubAgentState | None = None


class TUICommandRenderer:
    """Execute RenderCommand sequences and render them to the terminal.

    This is the only component that performs actual terminal rendering.
    """

    def __init__(self, theme: str | None = None, notifier: TerminalNotifier | None = None) -> None:
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)

        self._bottom_live: CropAboveLive | None = None
        self._stream_renderable: RenderableType | None = None
        self._stream_max_height: int = 0
        self._stream_last_height: int = 0
        self._stream_last_width: int = 0
        self._spinner_visible: bool = False
        self._spinner_last_update_key: tuple[object, object] | None = None

        self._status_text: ShimmerStatusText = ShimmerStatusText(STATUS_DEFAULT_TEXT)
        self._status_spinner: Spinner = BreathingSpinner(
            r_status.spinner_name(),
            text=SingleLine(self._status_text),
            style=ThemeKey.STATUS_SPINNER,
        )

        self._notifier = notifier
        self._assistant_stream = _StreamState()
        self._thinking_stream = _StreamState()

        self._sessions: dict[str, _SessionStatus] = {}
        self._current_sub_agent_color: Style | None = None
        self._sub_agent_color_index = 0

    # ---------------------------------------------------------------------
    # Session helpers
    # ---------------------------------------------------------------------

    def register_session(self, session_id: str, sub_agent_state: model.SubAgentState | None = None) -> None:
        st = _SessionStatus(sub_agent_state=sub_agent_state)
        if sub_agent_state is not None:
            color, color_index = self._pick_sub_agent_color()
            st.color = color
            st.color_index = color_index
        self._sessions[session_id] = st

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self._sessions and self._sessions[session_id].sub_agent_state is not None

    def _should_display_sub_agent_thinking_header(self, session_id: str) -> bool:
        # Hardcoded: only show sub-agent thinking headers for ImageGen.
        st = self._sessions.get(session_id)
        if st is None or st.sub_agent_state is None:
            return False
        return st.sub_agent_state.sub_agent_type == "ImageGen"

    def _advance_sub_agent_color_index(self) -> None:
        palette_size = len(self.themes.sub_agent_colors)
        if palette_size == 0:
            self._sub_agent_color_index = 0
            return
        self._sub_agent_color_index = (self._sub_agent_color_index + 1) % palette_size

    def _pick_sub_agent_color(self) -> tuple[Style, int]:
        self._advance_sub_agent_color_index()
        palette = self.themes.sub_agent_colors
        if not palette:
            return Style(), 0
        return palette[self._sub_agent_color_index], self._sub_agent_color_index

    def _get_session_sub_agent_color(self, session_id: str) -> Style:
        st = self._sessions.get(session_id)
        if st and st.color:
            return st.color
        return Style()

    @contextmanager
    def session_print_context(self, session_id: str) -> Iterator[None]:
        """Temporarily switch to sub-agent quote style."""

        st = self._sessions.get(session_id)
        if st is not None and st.color:
            self._current_sub_agent_color = st.color
        try:
            yield
        finally:
            self._current_sub_agent_color = None

    # ---------------------------------------------------------------------
    # Low-level printing & bottom status
    # ---------------------------------------------------------------------

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n") -> None:
        if self._current_sub_agent_color:
            if objects:
                content = objects[0] if len(objects) == 1 else objects
                self.console.print(Quote(content, style=self._current_sub_agent_color), overflow="ellipsis")
            return
        self.console.print(*objects, style=style, end=end, overflow="ellipsis")

    def spinner_start(self) -> None:
        self._spinner_visible = True
        self._ensure_bottom_live_started()
        self._refresh_bottom_live()

    def spinner_stop(self) -> None:
        self._spinner_visible = False
        self._refresh_bottom_live()

    def spinner_update(self, status_text: str | Text, right_text: RenderableType | None = None) -> None:
        new_key = (self._spinner_text_key(status_text), self._spinner_right_text_key(right_text))
        if self._spinner_last_update_key == new_key:
            return
        self._spinner_last_update_key = new_key

        self._status_text = ShimmerStatusText(status_text, right_text)
        self._status_spinner.update(text=SingleLine(self._status_text), style=ThemeKey.STATUS_SPINNER)
        self._refresh_bottom_live()

    @staticmethod
    def _spinner_text_key(text: str | Text) -> object:
        if isinstance(text, Text):
            style = str(text.style) if text.style else ""
            return ("Text", text.plain, style)
        return ("str", text)

    @staticmethod
    def _spinner_right_text_key(text: RenderableType | None) -> object:
        if text is None:
            return ("none",)
        if isinstance(text, Text):
            style = str(text.style) if text.style else ""
            return ("Text", text.plain, style)
        if isinstance(text, str):
            return ("str", text)
        # Fall back to a unique key so we never skip updates for dynamic renderables.
        return ("other", object())

    def set_stream_renderable(self, renderable: RenderableType | None) -> None:
        if renderable is None:
            self._stream_renderable = None
            self._stream_max_height = 0
            self._stream_last_height = 0
            self._stream_last_width = 0
            self._refresh_bottom_live()
            return

        self._ensure_bottom_live_started()
        self._stream_renderable = renderable

        height = len(self.console.render_lines(renderable, self.console.options, pad=False))
        self._stream_last_height = height
        self._stream_last_width = self.console.size.width

        if self._stream_max_height - height > STREAM_MAX_HEIGHT_SHRINK_RESET_LINES:
            self._stream_max_height = height
        else:
            self._stream_max_height = max(self._stream_max_height, height)
        self._refresh_bottom_live()

    def _ensure_bottom_live_started(self) -> None:
        if self._bottom_live is not None:
            return
        self._bottom_live = CropAboveLive(
            Text(""),
            console=self.console,
            refresh_per_second=30,
            transient=True,
            redirect_stdout=False,
            redirect_stderr=False,
        )
        self._bottom_live.start()

    def _bottom_renderable(self) -> RenderableType:
        stream_part: RenderableType = Group()
        gap_part: RenderableType = Group()

        if MARKDOWN_STREAM_LIVE_REPAINT_ENABLED:
            stream = self._stream_renderable
            if stream is not None:
                current_width = self.console.size.width
                if self._stream_last_width != current_width:
                    height = len(self.console.render_lines(stream, self.console.options, pad=False))
                    self._stream_last_height = height
                    self._stream_last_width = current_width

                    if self._stream_max_height - height > STREAM_MAX_HEIGHT_SHRINK_RESET_LINES:
                        self._stream_max_height = height
                    else:
                        self._stream_max_height = max(self._stream_max_height, height)
                else:
                    height = self._stream_last_height

                pad_lines = max(self._stream_max_height - height, 0)
                if pad_lines:
                    stream = Padding(stream, (0, 0, pad_lines, 0))
                stream_part = stream

            gap_part = Text("") if self._spinner_visible else Group()

        status_part: RenderableType = SingleLine(self._status_spinner) if self._spinner_visible else Group()
        return Group(stream_part, gap_part, status_part)

    def _refresh_bottom_live(self) -> None:
        if self._bottom_live is None:
            return
        self._bottom_live.update(self._bottom_renderable(), refresh=True)

    def stop_bottom_live(self) -> None:
        if self._bottom_live is None:
            return
        with contextlib.suppress(Exception):
            # Avoid cursor restore when stopping right before prompt_toolkit.
            self._bottom_live.transient = False
            self._bottom_live.stop()
        self._bottom_live = None

    # ---------------------------------------------------------------------
    # Stream helpers (MarkdownStream)
    # ---------------------------------------------------------------------

    def _new_thinking_mdstream(self) -> MarkdownStream:
        return MarkdownStream(
            mdargs={
                "code_theme": self.themes.code_theme,
                "style": ThemeKey.THINKING,
            },
            theme=self.themes.thinking_markdown_theme,
            console=self.console,
            live_sink=None,
            mark=c_thinking.THINKING_MESSAGE_MARK,
            mark_style=ThemeKey.THINKING,
            left_margin=MARKDOWN_LEFT_MARGIN,
            markdown_class=ThinkingMarkdown,
        )

    def _new_assistant_mdstream(self) -> MarkdownStream:
        return MarkdownStream(
            mdargs={"code_theme": self.themes.code_theme},
            theme=self.themes.markdown_theme,
            console=self.console,
            live_sink=self.set_stream_renderable,
            mark=c_assistant.ASSISTANT_MESSAGE_MARK,
            left_margin=MARKDOWN_LEFT_MARGIN,
        )

    def _flush_thinking(self) -> None:
        self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)

    def _flush_assistant(self) -> None:
        self._assistant_stream.render()

    # ---------------------------------------------------------------------
    # Event-specific rendering helpers
    # ---------------------------------------------------------------------

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        if c_tools.is_sub_agent_tool(e.tool_name):
            return
        renderable = c_tools.render_tool_call(e)
        if renderable is not None:
            self.print(renderable)

    def display_tool_call_result(self, e: events.ToolResultEvent, *, is_sub_agent: bool = False) -> None:
        if c_tools.is_sub_agent_tool(e.tool_name):
            return

        if is_sub_agent and e.is_error:
            error_msg = truncate_head(e.result)
            self.print(c_errors.render_tool_error(error_msg))
            return

        if not is_sub_agent and e.tool_name == tools.MERMAID and isinstance(e.ui_extra, model.MermaidLinkUIExtra):
            image_path = c_mermaid_viewer.download_mermaid_png(
                link=e.ui_extra.link,
                tool_call_id=e.tool_call_id,
                session_id=e.session_id,
            )
            if image_path is not None:
                self.display_image(str(image_path), height=None)

        renderable = c_tools.render_tool_result(e, code_theme=self.themes.code_theme, session_id=e.session_id)
        if renderable is not None:
            self.print(renderable)

    def display_thinking(self, content: str) -> None:
        renderable = c_thinking.render_thinking(
            content,
            code_theme=self.themes.code_theme,
            style=ThemeKey.THINKING,
        )
        if renderable is not None:
            self.console.push_theme(theme=self.themes.thinking_markdown_theme)
            self.print(renderable)
            self.console.pop_theme()
            self.print()

    def display_thinking_header(self, header: str) -> None:
        stripped = header.strip()
        if not stripped:
            return
        self.print(
            Text.assemble(
                (c_thinking.THINKING_MESSAGE_MARK, ThemeKey.THINKING),
                " ",
                (stripped, ThemeKey.THINKING_BOLD),
            )
        )

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        self.print()
        for event in history_events.events:
            event_session_id = getattr(event, "session_id", history_events.session_id)
            is_sub_agent = self.is_sub_agent_session(event_session_id)

            with self.session_print_context(event_session_id):
                match event:
                    case events.TaskStartEvent() as e:
                        self.display_task_start(e)
                    case events.TurnStartEvent():
                        self.print()
                    case events.AssistantImageDeltaEvent() as e:
                        self.display_image(e.file_path)
                    case events.ResponseCompleteEvent() as e:
                        if is_sub_agent:
                            if self._should_display_sub_agent_thinking_header(event_session_id) and e.thinking_text:
                                header = c_thinking.extract_last_bold_header(
                                    c_thinking.normalize_thinking_content(e.thinking_text)
                                )
                                if header:
                                    self.display_thinking_header(header)
                            continue
                        if e.thinking_text:
                            self.display_thinking(e.thinking_text)
                        renderable = c_assistant.render_assistant_message(e.content, code_theme=self.themes.code_theme)
                        if renderable is not None:
                            self.print(renderable)
                            self.print()
                    case events.DeveloperMessageEvent() as e:
                        self.display_developer_message(e)
                    case events.UserMessageEvent() as e:
                        if is_sub_agent:
                            continue
                        self.print(c_user_input.render_user_input(e.content))
                    case events.ToolCallEvent() as e:
                        tool_call_dict[e.tool_call_id] = e
                    case events.ToolResultEvent() as e:
                        tool_call_event = tool_call_dict.get(e.tool_call_id)
                        if tool_call_event is not None:
                            self.display_tool_call(tool_call_event)
                        tool_call_dict.pop(e.tool_call_id, None)
                        if is_sub_agent:
                            continue
                        self.display_tool_call_result(e)
                    case events.TaskMetadataEvent() as e:
                        self.print(c_metadata.render_task_metadata(e))
                        self.print()
                    case events.InterruptEvent():
                        self.print()
                        self.print(c_user_input.render_interrupt())
                    case events.ErrorEvent() as e:
                        self.display_error(e)
                    case events.TaskFinishEvent() as e:
                        self.display_task_finish(e)

    def display_developer_message(self, e: events.DeveloperMessageEvent) -> None:
        if not c_developer.need_render_developer_message(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_developer.render_developer_message(e))

    def display_command_output(self, e: events.CommandOutputEvent) -> None:
        with self.session_print_context(e.session_id):
            self.print(c_command_output.render_command_output(e))
            self.print()

    def display_welcome(self, event: events.WelcomeEvent) -> None:
        self.print(c_welcome.render_welcome(event))

    def display_user_message(self, event: events.UserMessageEvent) -> None:
        self.print(c_user_input.render_user_input(event.content))

    def display_task_start(self, event: events.TaskStartEvent) -> None:
        self.register_session(event.session_id, event.sub_agent_state)
        if event.sub_agent_state is not None:
            with self.session_print_context(event.session_id):
                self.print(
                    c_sub_agent.render_sub_agent_call(
                        event.sub_agent_state,
                        self._get_session_sub_agent_color(event.session_id),
                    )
                )

    def display_turn_start(self, event: events.TurnStartEvent) -> None:
        if not self.is_sub_agent_session(event.session_id):
            self.print()

    def display_image(self, file_path: str, height: int | None = 40) -> None:
        # Suspend the Live status bar while emitting raw terminal output.
        had_live = self._bottom_live is not None
        was_spinner_visible = self._spinner_visible
        has_stream = MARKDOWN_STREAM_LIVE_REPAINT_ENABLED and self._stream_renderable is not None
        resume_live = had_live and (was_spinner_visible or has_stream)

        if self._bottom_live is not None:
            with contextlib.suppress(Exception):
                self._bottom_live.stop()
            self._bottom_live = None

        try:
            print_kitty_image(file_path, height=height, file=self.console.file)
        finally:
            if resume_live:
                if was_spinner_visible:
                    self.spinner_start()
                else:
                    self._ensure_bottom_live_started()
                    self._refresh_bottom_live()

    def display_task_metadata(self, event: events.TaskMetadataEvent) -> None:
        if self.is_sub_agent_session(event.session_id):
            return
        self.print(c_metadata.render_task_metadata(event))
        self.print()

    def display_task_finish(self, event: events.TaskFinishEvent) -> None:
        if self.is_sub_agent_session(event.session_id):
            st = self._sessions.get(event.session_id)
            description = st.sub_agent_state.sub_agent_desc if st and st.sub_agent_state else None
            with self.session_print_context(event.session_id):
                self.print(
                    c_sub_agent.render_sub_agent_result(
                        event.task_result,
                        has_structured_output=event.has_structured_output,
                        description=description,
                        sub_agent_color=self._current_sub_agent_color,
                    )
                )

    def display_interrupt(self) -> None:
        self.print(c_user_input.render_interrupt())

    def display_error(self, event: events.ErrorEvent) -> None:
        if event.session_id:
            with self.session_print_context(event.session_id):
                self.print(c_errors.render_error(Text(event.error_message)))
        else:
            self.print(c_errors.render_error(Text(event.error_message)))

    # ---------------------------------------------------------------------
    # Notifications
    # ---------------------------------------------------------------------

    def _maybe_notify_task_finish(self, event: RenderTaskFinish) -> None:
        if self._notifier is None:
            return
        if self.is_sub_agent_session(event.event.session_id):
            return
        body = self._compact_result_text(event.event.task_result)
        notification = Notification(
            type=NotificationType.AGENT_TASK_COMPLETE,
            title="Task Completed",
            body=body,
        )
        self._notifier.notify(notification)

    def _compact_result_text(self, text: str) -> str | None:
        stripped = text.strip()
        if not stripped:
            return None
        squashed = " ".join(stripped.split())
        if len(squashed) > 200:
            return squashed[:197] + "…"
        return squashed

    # ---------------------------------------------------------------------
    # RenderCommand executor
    # ---------------------------------------------------------------------

    async def execute(self, commands: list[RenderCommand]) -> None:
        for cmd in commands:
            match cmd:
                case RenderReplayHistory(event=event):
                    await self.replay_history(event)
                    self.spinner_stop()
                case RenderWelcome(event=event):
                    self.display_welcome(event)
                case RenderUserMessage(event=event):
                    self.display_user_message(event)
                case RenderTaskStart(event=event):
                    self.display_task_start(event)
                case RenderDeveloperMessage(event=event):
                    self.display_developer_message(event)
                case RenderCommandOutput(event=event):
                    self.display_command_output(event)
                case RenderTurnStart(event=event):
                    self.display_turn_start(event)
                case StartThinkingStream():
                    if not self._thinking_stream.is_active:
                        self._thinking_stream.start(self._new_thinking_mdstream())
                case AppendThinking(content=content):
                    if self._thinking_stream.is_active:
                        first_delta = self._thinking_stream.buffer == ""
                        self._thinking_stream.append(content)
                        if first_delta:
                            self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)
                        self._flush_thinking()
                case EndThinkingStream():
                    finalized = self._thinking_stream.finalize(transform=c_thinking.normalize_thinking_content)
                    if finalized:
                        self.print()
                case StartAssistantStream():
                    if not self._assistant_stream.is_active:
                        self._assistant_stream.start(self._new_assistant_mdstream())
                case AppendAssistant(content=content):
                    if self._assistant_stream.is_active:
                        first_delta = self._assistant_stream.buffer == ""
                        self._assistant_stream.append(content)
                        if first_delta:
                            self._assistant_stream.render()
                        self._flush_assistant()
                case EndAssistantStream():
                    finalized = self._assistant_stream.finalize()
                    if finalized:
                        self.print()
                case RenderThinkingHeader(session_id=session_id, header=header):
                    with self.session_print_context(session_id):
                        self.display_thinking_header(header)
                case RenderAssistantImage(file_path=file_path):
                    self.display_image(file_path)
                case RenderToolCall(event=event):
                    with self.session_print_context(event.session_id):
                        self.display_tool_call(event)
                case RenderToolResult(event=event, is_sub_agent_session=is_sub_agent_session):
                    with self.session_print_context(event.session_id):
                        self.display_tool_call_result(event, is_sub_agent=is_sub_agent_session)
                case RenderTaskMetadata(event=event):
                    self.display_task_metadata(event)
                case RenderTaskFinish() as cmd_finish:
                    self.display_task_finish(cmd_finish.event)
                    self._maybe_notify_task_finish(cmd_finish)
                case RenderInterrupt():
                    self.display_interrupt()
                case RenderError(event=event):
                    self.display_error(event)
                case SpinnerStart():
                    self.spinner_start()
                case SpinnerStop():
                    self.spinner_stop()
                case SpinnerUpdate(status_text=status_text, right_text=right_text):
                    self.spinner_update(status_text, right_text)
                case PrintBlankLine():
                    self.print()
                case PrintRuleLine():
                    self.console.print(Rule(characters="─", style=ThemeKey.LINES))
                case EmitOsc94Error():
                    emit_osc94(OSC94States.ERROR)
                case EmitTmuxSignal():
                    emit_tmux_signal()
                case TaskClockStart():
                    r_status.set_task_start()
                case TaskClockClear():
                    r_status.clear_task_start()
                case _:
                    continue

    async def stop(self) -> None:
        self._flush_assistant()
        self._flush_thinking()
        with contextlib.suppress(Exception):
            self.spinner_stop()
