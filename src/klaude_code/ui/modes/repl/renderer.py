from __future__ import annotations

import contextlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich.console import Console, Group, RenderableType
from rich.padding import Padding
from rich.spinner import Spinner
from rich.style import Style, StyleType
from rich.text import Text

from klaude_code import const
from klaude_code.protocol import events, model
from klaude_code.ui.renderers import assistant as r_assistant
from klaude_code.ui.renderers import developer as r_developer
from klaude_code.ui.renderers import errors as r_errors
from klaude_code.ui.renderers import metadata as r_metadata
from klaude_code.ui.renderers import sub_agent as r_sub_agent
from klaude_code.ui.renderers import thinking as r_thinking
from klaude_code.ui.renderers import tools as r_tools
from klaude_code.ui.renderers import user_input as r_user_input
from klaude_code.ui.renderers.common import truncate_display
from klaude_code.ui.rich import status as r_status
from klaude_code.ui.rich.live import CropAboveLive, SingleLine
from klaude_code.ui.rich.quote import Quote
from klaude_code.ui.rich.status import BreathingSpinner, ShimmerStatusText
from klaude_code.ui.rich.theme import ThemeKey, get_theme


@dataclass
class SessionStatus:
    color: Style | None = None
    color_index: int | None = None
    sub_agent_state: model.SubAgentState | None = None


class REPLRenderer:
    """Render REPL content via a Rich console."""

    def __init__(self, theme: str | None = None):
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)
        self._bottom_live: CropAboveLive | None = None
        self._stream_renderable: RenderableType | None = None
        self._stream_max_height: int = 0
        self._stream_last_height: int = 0
        self._stream_last_width: int = 0
        self._spinner_visible: bool = False

        self._status_text: ShimmerStatusText = ShimmerStatusText(const.STATUS_DEFAULT_TEXT)
        self._status_spinner: Spinner = BreathingSpinner(
            r_status.spinner_name(),
            text=SingleLine(self._status_text),
            style=ThemeKey.STATUS_SPINNER,
        )

        self.session_map: dict[str, SessionStatus] = {}
        self.current_sub_agent_color: Style | None = None
        self.sub_agent_color_index = 0

    def register_session(self, session_id: str, sub_agent_state: model.SubAgentState | None = None) -> None:
        session_status = SessionStatus(
            sub_agent_state=sub_agent_state,
        )
        if sub_agent_state is not None:
            color, color_index = self.pick_sub_agent_color()
            session_status.color = color
            session_status.color_index = color_index
        self.session_map[session_id] = session_status

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self.session_map and self.session_map[session_id].sub_agent_state is not None

    def _advance_sub_agent_color_index(self) -> None:
        palette_size = len(self.themes.sub_agent_colors)
        if palette_size == 0:
            self.sub_agent_color_index = 0
            return
        self.sub_agent_color_index = (self.sub_agent_color_index + 1) % palette_size

    def pick_sub_agent_color(self) -> tuple[Style, int]:
        self._advance_sub_agent_color_index()
        palette = self.themes.sub_agent_colors
        if not palette:
            return Style(), 0
        return palette[self.sub_agent_color_index], self.sub_agent_color_index

    def get_session_sub_agent_color(self, session_id: str) -> Style:
        status = self.session_map.get(session_id)
        if status and status.color:
            return status.color
        return Style()

    def get_session_sub_agent_background(self, session_id: str) -> Style:
        status = self.session_map.get(session_id)
        backgrounds = self.themes.sub_agent_backgrounds
        if status and status.color_index is not None and backgrounds:
            return backgrounds[status.color_index]
        return Style()

    @contextmanager
    def session_print_context(self, session_id: str) -> Iterator[None]:
        """Temporarily switch to sub-agent quote style."""
        if session_id in self.session_map and self.session_map[session_id].color:
            self.current_sub_agent_color = self.session_map[session_id].color
        try:
            yield
        finally:
            self.current_sub_agent_color = None

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n") -> None:
        if self.current_sub_agent_color:
            if objects:
                content = objects[0] if len(objects) == 1 else objects
                self.console.print(Quote(content, style=self.current_sub_agent_color), overflow="ellipsis")
            return
        self.console.print(*objects, style=style, end=end, overflow="ellipsis")

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        if r_tools.is_sub_agent_tool(e.tool_name):
            return
        renderable = r_tools.render_tool_call(e)
        if renderable is not None:
            self.print(renderable)

    def display_tool_call_result(self, e: events.ToolResultEvent) -> None:
        if r_tools.is_sub_agent_tool(e.tool_name):
            return
        renderable = r_tools.render_tool_result(e, code_theme=self.themes.code_theme)
        if renderable is not None:
            self.print(renderable)

    def display_thinking(self, content: str) -> None:
        renderable = r_thinking.render_thinking(
            content,
            code_theme=self.themes.code_theme,
            style=ThemeKey.THINKING,
        )
        if renderable is not None:
            self.console.push_theme(theme=self.themes.thinking_markdown_theme)
            self.print(renderable)
            self.console.pop_theme()
            self.print()

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        for event in history_events.events:
            event_session_id = getattr(event, "session_id", history_events.session_id)
            is_sub_agent = self.is_sub_agent_session(event_session_id)

            with self.session_print_context(event_session_id):
                match event:
                    case events.TaskStartEvent() as e:
                        self.display_task_start(e)
                    case events.TurnStartEvent():
                        self.print()
                    case events.AssistantMessageEvent() as e:
                        if is_sub_agent:
                            continue
                        renderable = r_assistant.render_assistant_message(e.content, code_theme=self.themes.code_theme)
                        if renderable is not None:
                            self.print(renderable)
                            self.print()
                    case events.ThinkingEvent() as e:
                        if is_sub_agent:
                            continue
                        self.display_thinking(e.content)
                    case events.DeveloperMessageEvent() as e:
                        self.display_developer_message(e)
                        self.display_command_output(e)
                    case events.UserMessageEvent() as e:
                        if is_sub_agent:
                            continue
                        self.print(r_user_input.render_user_input(e.content))
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
                        self.print(r_metadata.render_task_metadata(e))
                        self.print()
                    case events.InterruptEvent():
                        self.print()
                        self.print(r_user_input.render_interrupt())
                    case events.ErrorEvent() as e:
                        self.display_error(e)
                    case events.TaskFinishEvent() as e:
                        self.display_task_finish(e)

    def display_developer_message(self, e: events.DeveloperMessageEvent) -> None:
        if not r_developer.need_render_developer_message(e):
            return
        with self.session_print_context(e.session_id):
            self.print(r_developer.render_developer_message(e))

    def display_command_output(self, e: events.DeveloperMessageEvent) -> None:
        if not e.item.command_output:
            return
        with self.session_print_context(e.session_id):
            self.print(r_developer.render_command_output(e))
            self.print()

    def display_welcome(self, event: events.WelcomeEvent) -> None:
        self.print(r_metadata.render_welcome(event))

    def display_user_message(self, event: events.UserMessageEvent) -> None:
        self.print(r_user_input.render_user_input(event.content))

    def display_task_start(self, event: events.TaskStartEvent) -> None:
        self.register_session(event.session_id, event.sub_agent_state)
        if event.sub_agent_state is not None:
            with self.session_print_context(event.session_id):
                self.print(
                    r_sub_agent.render_sub_agent_call(
                        event.sub_agent_state,
                        self.get_session_sub_agent_color(event.session_id),
                    )
                )

    def display_turn_start(self, event: events.TurnStartEvent) -> None:
        if not self.is_sub_agent_session(event.session_id):
            self.print()

    def display_assistant_message(self, content: str) -> None:
        renderable = r_assistant.render_assistant_message(content, code_theme=self.themes.code_theme)
        if renderable is not None:
            self.print(renderable)
            self.print()

    def display_task_metadata(self, event: events.TaskMetadataEvent) -> None:
        with self.session_print_context(event.session_id):
            self.print(r_metadata.render_task_metadata(event))
            self.print()

    def display_task_finish(self, event: events.TaskFinishEvent) -> None:
        if self.is_sub_agent_session(event.session_id):
            session_status = self.session_map.get(event.session_id)
            description = (
                session_status.sub_agent_state.sub_agent_desc
                if session_status and session_status.sub_agent_state
                else None
            )
            panel_style = self.get_session_sub_agent_background(event.session_id)
            with self.session_print_context(event.session_id):
                self.print(
                    r_sub_agent.render_sub_agent_result(
                        event.task_result,
                        code_theme=self.themes.code_theme,
                        has_structured_output=event.has_structured_output,
                        description=description,
                        panel_style=panel_style,
                    )
                )

    def display_interrupt(self) -> None:
        self.print(r_user_input.render_interrupt())

    def display_error(self, event: events.ErrorEvent) -> None:
        self.print(r_errors.render_error(truncate_display(event.error_message)))

    # -------------------------------------------------------------------------
    # Spinner control methods
    # -------------------------------------------------------------------------

    def spinner_start(self) -> None:
        """Start the spinner animation."""
        self._spinner_visible = True
        self._ensure_bottom_live_started()
        self._refresh_bottom_live()

    def spinner_stop(self) -> None:
        """Stop the spinner animation."""
        self._spinner_visible = False
        self._refresh_bottom_live()

    def spinner_update(self, status_text: str | Text, right_text: RenderableType | None = None) -> None:
        """Update the spinner status text with optional right-aligned text."""
        self._status_text = ShimmerStatusText(status_text, right_text)
        self._status_spinner.update(text=SingleLine(self._status_text), style=ThemeKey.STATUS_SPINNER)
        self._refresh_bottom_live()

    def spinner_renderable(self) -> Spinner:
        """Return the spinner's renderable for embedding in other components."""
        return self._status_spinner

    def set_stream_renderable(self, renderable: RenderableType | None) -> None:
        """Set the current streaming renderable displayed above the status line."""

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

        if const.MARKDOWN_STREAM_LIVE_REPAINT_ENABLED:
            stream = self._stream_renderable
            if stream is not None:
                current_width = self.console.size.width
                if self._stream_last_width != current_width:
                    height = len(self.console.render_lines(stream, self.console.options, pad=False))
                    self._stream_last_height = height
                    self._stream_last_width = current_width
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
