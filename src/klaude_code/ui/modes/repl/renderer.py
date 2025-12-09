from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from rich import box
from rich.box import Box
from rich.console import Console
from rich.spinner import Spinner
from rich.status import Status
from rich.style import Style, StyleType
from rich.text import Text

from klaude_code.protocol import events, model
from klaude_code.ui.renderers import assistant as r_assistant
from klaude_code.ui.renderers import developer as r_developer
from klaude_code.ui.renderers import errors as r_errors
from klaude_code.ui.renderers import metadata as r_metadata
from klaude_code.ui.renderers import sub_agent as r_sub_agent
from klaude_code.ui.renderers import thinking as r_thinking
from klaude_code.ui.renderers import tools as r_tools
from klaude_code.ui.renderers import user_input as r_user_input
from klaude_code.ui.rich import status as r_status
from klaude_code.ui.rich.quote import Quote
from klaude_code.ui.rich.status import ShimmerStatusText
from klaude_code.ui.rich.theme import ThemeKey, get_theme
from klaude_code.ui.utils.common import truncate_display


@dataclass
class SessionStatus:
    color: Style | None = None
    sub_agent_state: model.SubAgentState | None = None


class REPLRenderer:
    """Render REPL content via a Rich console."""

    def __init__(self, theme: str | None = None):
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)
        self._spinner: Status = self.console.status(
            ShimmerStatusText("Thinking …", ThemeKey.SPINNER_STATUS_TEXT),
            spinner=r_status.spinner_name(),
            spinner_style=ThemeKey.SPINNER_STATUS,
        )

        self.session_map: dict[str, SessionStatus] = {}
        self.current_sub_agent_color: Style | None = None
        self.sub_agent_color_index = 0

    def register_session(self, session_id: str, sub_agent_state: model.SubAgentState | None = None) -> None:
        session_status = SessionStatus(
            sub_agent_state=sub_agent_state,
        )
        if sub_agent_state is not None:
            session_status.color = self.pick_sub_agent_color()
        self.session_map[session_id] = session_status

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self.session_map and self.session_map[session_id].sub_agent_state is not None

    def _advance_sub_agent_color_index(self) -> None:
        palette_size = len(self.themes.sub_agent_colors)
        if palette_size == 0:
            self.sub_agent_color_index = 0
            return
        self.sub_agent_color_index = (self.sub_agent_color_index + 1) % palette_size

    def pick_sub_agent_color(self) -> Style:
        self._advance_sub_agent_color_index()
        palette = self.themes.sub_agent_colors
        if not palette:
            return Style()
        return palette[self.sub_agent_color_index]

    def get_session_sub_agent_color(self, session_id: str) -> Style:
        status = self.session_map.get(session_id)
        if status and status.color:
            return status.color
        return Style()

    def box_style(self) -> Box:
        return box.ROUNDED

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
        renderable = r_tools.render_tool_result(e)
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
                        self.display_thinking_prefix()
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
        self.print(r_metadata.render_welcome(event, box_style=self.box_style()))

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
            with self.session_print_context(event.session_id):
                self.print(
                    r_sub_agent.render_sub_agent_result(
                        event.task_result,
                        code_theme=self.themes.code_theme,
                        has_structured_output=event.has_structured_output,
                    )
                )

    def display_interrupt(self) -> None:
        self.print(r_user_input.render_interrupt())

    def display_error(self, event: events.ErrorEvent) -> None:
        self.print(
            r_errors.render_error(
                self.console.render_str(truncate_display(event.error_message)),
                indent=0,
            )
        )

    def display_thinking_prefix(self) -> None:
        self.print(r_thinking.thinking_prefix())

    # -------------------------------------------------------------------------
    # Spinner control methods
    # -------------------------------------------------------------------------

    def spinner_start(self) -> None:
        """Start the spinner animation."""
        self._spinner.start()

    def spinner_stop(self) -> None:
        """Stop the spinner animation."""
        self._spinner.stop()

    def spinner_update(self, status_text: str | Text, right_text: Text | None = None) -> None:
        """Update the spinner status text with optional right-aligned text."""
        self._spinner.update(ShimmerStatusText(status_text, ThemeKey.SPINNER_STATUS_TEXT, right_text))

    def spinner_renderable(self) -> Spinner:
        """Return the spinner's renderable for embedding in other components."""
        return self._spinner.renderable
