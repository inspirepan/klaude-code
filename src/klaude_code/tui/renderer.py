from __future__ import annotations

import contextlib
import shutil
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.panel import Panel
from rich.rule import Rule
from rich.spinner import Spinner
from rich.style import Style, StyleType
from rich.text import Text

from klaude_code.const import (
    MARKDOWN_LEFT_MARGIN,
    MARKDOWN_RIGHT_MARGIN,
    MARKDOWN_STREAM_LIVE_REPAINT_ENABLED,
    STATUS_DEFAULT_TEXT,
    STREAM_MAX_HEIGHT_SHRINK_RESET_LINES,
)
from klaude_code.protocol import events, model, tools
from klaude_code.tui.commands import (
    AppendAssistant,
    AppendBashCommandOutput,
    AppendThinking,
    EmitOsc94Error,
    EmitTmuxSignal,
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    PrintRuleLine,
    RenderAssistantImage,
    RenderBashCommandEnd,
    RenderBashCommandStart,
    RenderCommand,
    RenderCommandOutput,
    RenderCompactionSummary,
    RenderDeveloperMessage,
    RenderError,
    RenderInterrupt,
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
from klaude_code.tui.components.common import create_grid, truncate_head
from klaude_code.tui.components.rich import status as r_status
from klaude_code.tui.components.rich.live import CropAboveLive, SingleLine
from klaude_code.tui.components.rich.markdown import MarkdownStream, NoInsetMarkdown, ThinkingMarkdown
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

        # Replay mode reuses the same event/state machine but does not need streaming UI.
        # When enabled, we avoid bottom Live rendering and defer markdown rendering until
        # the corresponding stream End event.
        self._replay_mode: bool = False

        self._bash_stream_active: bool = False
        self._bash_last_char_was_newline: bool = True

        self._sessions: dict[str, _SessionStatus] = {}
        self._current_sub_agent_color: Style | None = None
        self._sub_agent_color_index = 0
        self._sub_agent_thinking_buffers: dict[str, str] = {}

    def set_replay_mode(self, enabled: bool) -> None:
        """Enable or disable replay rendering mode.

        Replay mode is optimized for speed and stability:
        - Avoid Rich Live / bottom status rendering.
        - Defer markdown stream rendering until End events.
        """

        self._replay_mode = enabled

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
        # Keep a visible separation between the bottom status line (spinner)
        # and the main terminal output.
        gap_part: RenderableType = Text(" ") if (self._spinner_visible and self._bash_stream_active) else Group()

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
                gap_part = Text(" ") if (self._spinner_visible and self._bash_stream_active) else Group()

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
            right_margin=MARKDOWN_RIGHT_MARGIN,
            markdown_class=ThinkingMarkdown,
        )

    def _new_assistant_mdstream(self) -> MarkdownStream:
        live_sink = None if self._replay_mode else self.set_stream_renderable
        return MarkdownStream(
            mdargs={"code_theme": self.themes.code_theme},
            theme=self.themes.markdown_theme,
            console=self.console,
            live_sink=live_sink,
            left_margin=MARKDOWN_LEFT_MARGIN,
            right_margin=MARKDOWN_RIGHT_MARGIN,
            image_callback=self.display_image,
        )

    def _flush_thinking(self) -> None:
        self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)

    def _flush_assistant(self) -> None:
        self._assistant_stream.render()

    def _render_sub_agent_thinking(self, content: str) -> None:
        """Render sub-agent thinking content as a single block."""
        normalized = c_thinking.normalize_thinking_content(content)
        if not normalized.strip():
            return
        md = ThinkingMarkdown(normalized, code_theme=self.themes.code_theme, style=ThemeKey.THINKING)
        self.console.push_theme(self.themes.thinking_markdown_theme)
        grid = create_grid()
        grid.add_row(Text(c_thinking.THINKING_MESSAGE_MARK, style=ThemeKey.THINKING), md)
        self.print(grid)
        self.console.pop_theme()
        self.print()

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
                self.display_image(str(image_path))

        if not is_sub_agent and isinstance(e.ui_extra, model.ImageUIExtra):
            self.display_image(e.ui_extra.file_path)

        renderable = c_tools.render_tool_result(e, code_theme=self.themes.code_theme, session_id=e.session_id)
        if renderable is not None:
            self.print(renderable)

    def display_thinking_header(self, header: str) -> None:
        stripped = header.strip()
        if not stripped:
            return
        self.print(
            Text.assemble(
                (c_thinking.THINKING_MESSAGE_MARK, ThemeKey.THINKING),
                " ",
                (stripped, ThemeKey.THINKING),
            )
        )

    def display_developer_message(self, e: events.DeveloperMessageEvent) -> None:
        if not c_developer.need_render_developer_message(e):
            return
        with self.session_print_context(e.session_id):
            self.print(c_developer.render_developer_message(e))

        # Display images from @ file references and user attachments
        if e.item.ui_extra:
            for ui_item in e.item.ui_extra.items:
                if isinstance(ui_item, (model.AtFileImagesUIItem, model.UserImagesUIItem)):
                    for image_path in ui_item.paths:
                        self.display_image(image_path)

    def display_command_output(self, e: events.CommandOutputEvent) -> None:
        with self.session_print_context(e.session_id):
            self.print(c_command_output.render_command_output(e))
            self.print()

    def display_bash_command_start(self, e: events.BashCommandStartEvent) -> None:
        # The user input line already shows `!cmd`; bash output is streamed as it arrives.
        # We keep minimal rendering here to avoid adding noise.
        self._bash_stream_active = True
        self._bash_last_char_was_newline = True
        if self._spinner_visible:
            self._refresh_bottom_live()

    def display_bash_command_delta(self, e: events.BashCommandOutputDeltaEvent) -> None:
        if not self._bash_stream_active:
            self._bash_stream_active = True
            if self._spinner_visible:
                self._refresh_bottom_live()

        content = e.content
        if content == "":
            return

        # Rich Live refreshes periodically (even when the renderable doesn't change).
        # If we print bash output without a trailing newline while Live is active,
        # the next refresh can overwrite the partial line.
        #
        # To keep streamed bash output stable, temporarily stop the bottom Live
        # during the print, and only resume it once the output is back at a
        # line boundary (i.e. chunk ends with "\n").
        if self._bottom_live is not None:
            with contextlib.suppress(Exception):
                self._bottom_live.stop()
            self._bottom_live = None

        try:
            # Do not use Renderer.print() here because it forces overflow="ellipsis",
            # which would truncate long command output lines.
            self.console.print(Text(content, style=ThemeKey.TOOL_RESULT), end="", overflow="ignore")
            self._bash_last_char_was_newline = content.endswith("\n")
        finally:
            # Resume the bottom Live only when we're not in the middle of a line,
            # otherwise periodic refresh can clobber the partial line.
            if self._bash_last_char_was_newline and self._spinner_visible:
                self._ensure_bottom_live_started()
                self._refresh_bottom_live()

    def display_bash_command_end(self, e: events.BashCommandEndEvent) -> None:
        # Stop the bottom Live before finalizing bash output to prevent a refresh
        # from interfering with the final line(s) written to stdout.
        if self._bottom_live is not None:
            with contextlib.suppress(Exception):
                self._bottom_live.stop()
            self._bottom_live = None

        # Leave a blank line before the next prompt:
        # - If the command output already ended with a newline, print one more "\n".
        # - Otherwise, print "\n\n" to end the line and add one empty line.
        if self._bash_stream_active:
            sep = "\n" if self._bash_last_char_was_newline else "\n\n"
            self.console.print(Text(sep), end="", overflow="ignore")

        self._bash_stream_active = False
        self._bash_last_char_was_newline = True

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

    def display_image(self, file_path: str) -> None:
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
            print_kitty_image(file_path, file=self.console.file)
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

    def display_compaction_summary(self, summary: str, kept_items_brief: tuple[tuple[str, int, str], ...] = ()) -> None:
        stripped = summary.strip()
        if not stripped:
            return
        stripped = (
            stripped.replace("<summary>", "")
            .replace("</summary>", "")
            .replace("<read_files>", "")
            .replace("</read_files>", "")
            .replace("<modified-files>", "")
            .replace("</modified-files>", "")
        )
        self.console.print(
            Rule(
                Text("Context Compacted", style=ThemeKey.COMPACTION_SUMMARY),
                characters="=",
                style=ThemeKey.LINES,
            )
        )
        self.print()

        # Limit panel width to min(100, terminal_width) minus left indent (2)
        terminal_width = shutil.get_terminal_size().columns
        panel_width = min(100, terminal_width) - 2

        self.console.push_theme(self.themes.markdown_theme)
        panel = Panel(
            NoInsetMarkdown(stripped, code_theme=self.themes.code_theme, style=ThemeKey.COMPACTION_SUMMARY),
            box=box.SIMPLE,
            border_style=ThemeKey.LINES,
            style=ThemeKey.COMPACTION_SUMMARY_PANEL,
            width=panel_width,
        )
        self.print(Padding(panel, (0, 0, 0, MARKDOWN_LEFT_MARGIN)))
        self.console.pop_theme()

        if kept_items_brief:
            # Collect tool call counts (skip User/Assistant entries)
            tool_counts: dict[str, int] = {}
            for item_type, count, _ in kept_items_brief:
                if item_type not in ("User", "Assistant"):
                    tool_counts[item_type] = tool_counts.get(item_type, 0) + count

            if tool_counts:
                parts: list[str] = []
                for tool_type, tool_count in tool_counts.items():
                    if tool_count > 1:
                        parts.append(f"{tool_type} x {tool_count}")
                    else:
                        parts.append(tool_type)
                line = Text()
                line.append("\n  Kept uncompacted: ", style=ThemeKey.COMPACTION_SUMMARY)
                line.append(", ".join(parts), style=ThemeKey.COMPACTION_SUMMARY)
                self.print(line)

        self.print()

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
                case RenderBashCommandStart(event=event):
                    self.display_bash_command_start(event)
                case AppendBashCommandOutput(event=event):
                    self.display_bash_command_delta(event)
                case RenderBashCommandEnd(event=event):
                    self.display_bash_command_end(event)
                case RenderTurnStart(event=event):
                    self.display_turn_start(event)
                case StartThinkingStream(session_id=session_id):
                    if self.is_sub_agent_session(session_id):
                        self._sub_agent_thinking_buffers[session_id] = ""
                    elif not self._thinking_stream.is_active:
                        self._thinking_stream.start(self._new_thinking_mdstream())
                case AppendThinking(session_id=session_id, content=content):
                    if self.is_sub_agent_session(session_id):
                        if session_id in self._sub_agent_thinking_buffers:
                            self._sub_agent_thinking_buffers[session_id] += content
                    elif self._thinking_stream.is_active:
                        self._thinking_stream.append(content)
                        if not self._replay_mode:
                            first_delta = self._thinking_stream.buffer == ""
                            if first_delta:
                                self._thinking_stream.render(transform=c_thinking.normalize_thinking_content)
                            self._flush_thinking()
                case EndThinkingStream(session_id=session_id):
                    if self.is_sub_agent_session(session_id):
                        buf = self._sub_agent_thinking_buffers.pop(session_id, "")
                        if buf.strip():
                            with self.session_print_context(session_id):
                                self._render_sub_agent_thinking(buf)
                    else:
                        had_content = bool(self._thinking_stream.buffer.strip())
                        finalized = self._thinking_stream.finalize(transform=c_thinking.normalize_thinking_content)
                        if finalized and had_content:
                            self.print()
                case StartAssistantStream(session_id=_):
                    if not self._assistant_stream.is_active:
                        self._assistant_stream.start(self._new_assistant_mdstream())
                case AppendAssistant(session_id=_, content=content):
                    if self._assistant_stream.is_active:
                        self._assistant_stream.append(content)
                        if not self._replay_mode:
                            first_delta = self._assistant_stream.buffer == ""
                            if first_delta:
                                self._assistant_stream.render()
                            self._flush_assistant()
                case EndAssistantStream(session_id=_):
                    had_content = bool(self._assistant_stream.buffer.strip())
                    finalized = self._assistant_stream.finalize()
                    if finalized and had_content:
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
                case RenderCompactionSummary(summary=summary, kept_items_brief=kept_items_brief):
                    self.display_compaction_summary(summary, kept_items_brief)
                case SpinnerStart():
                    self.spinner_start()
                case SpinnerStop():
                    self.spinner_stop()
                case SpinnerUpdate(status_text=status_text, right_text=right_text):
                    self.spinner_update(status_text, right_text)
                case PrintBlankLine():
                    self.print()
                case PrintRuleLine():
                    self.console.print(Rule(characters="─", style=ThemeKey.LINES_DIM))
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
