from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from rich import box
from rich.box import Box
from rich.console import Console
from rich.padding import Padding
from rich.status import Status
from rich.style import Style, StyleType
from rich.text import Text

from codex_mini.protocol import events, tools
from codex_mini.ui.mdstream import NoInsetMarkdown
from codex_mini.ui.quote import Quote
from codex_mini.ui.renderers import annotations as r_annotations
from codex_mini.ui.renderers import developer as r_developer
from codex_mini.ui.renderers import diffs as r_diffs
from codex_mini.ui.renderers import errors as r_errors
from codex_mini.ui.renderers import metadata as r_metadata
from codex_mini.ui.renderers import status as r_status
from codex_mini.ui.renderers import thinking as r_thinking
from codex_mini.ui.renderers import tools as r_tools
from codex_mini.ui.renderers import user_input as r_user_input
from codex_mini.ui.renderers.common import truncate_display
from codex_mini.ui.theme import ThemeKey, get_theme


@dataclass
class SessionStatus:
    is_subagent: bool = False
    color: Style | None = None
    sub_agent_type: tools.SubAgentType | None = None


class REPLRenderer:
    """Render REPL content via a Rich console."""

    def __init__(self, theme: str | None = None):
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)
        self.spinner: Status = self.console.status(
            r_status.render_status_text("Thinking …", ThemeKey.SPINNER_STATUS_BOLD),
            spinner=r_status.spinner_name(),
            spinner_style=ThemeKey.SPINNER_STATUS,
        )

        self.session_map: dict[str, SessionStatus] = {}
        self.current_session_status: SessionStatus | None = None
        self.subagent_color_index = -1
        self.subagent_color: Style = self.pick_sub_agent_color()

    def register_session(self, session_id: str, status: SessionStatus) -> None:
        self.session_map[session_id] = status

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self.session_map and self.session_map[session_id].is_subagent

    def pick_sub_agent_color(self, sub_agent_type: tools.SubAgentType | None = None) -> Style:
        if sub_agent_type and sub_agent_type == tools.SubAgentType.ORACLE:
            self.subagent_color = self.console.get_style(ThemeKey.SUB_AGENT_ORACLE)
        else:
            self.subagent_color_index = (self.subagent_color_index + 1) % len(self.themes.sub_agent_colors)
            self.subagent_color = self.themes.sub_agent_colors[self.subagent_color_index]
        return self.subagent_color

    def get_sub_agent_color(self) -> Style:
        return self.subagent_color

    def box_style(self) -> Box:
        return box.ROUNDED

    @contextmanager
    def session_print_context(self, session_id: str) -> Iterator[None]:
        """Temporarily switch to sub-agent quote style."""

        previous_status = self.current_session_status
        if session_id in self.session_map:
            self.current_session_status = self.session_map[session_id]
        try:
            yield
        finally:
            self.current_session_status = previous_status

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n") -> None:
        if (
            self.current_session_status
            and self.current_session_status.is_subagent
            and self.current_session_status.color
        ):
            if objects:
                self.console.print(Quote(*objects, style=self.current_session_status.color))
            else:
                self.console.print(Quote("", style=self.current_session_status.color))
            return
        self.console.print(*objects, style=style, end=end)

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        match e.tool_name:
            case tools.READ:
                self.print(r_tools.render_read_tool_call(e.arguments))
            case tools.EDIT:
                self.print(r_tools.render_edit_tool_call(e.arguments))
            case tools.MULTI_EDIT:
                self.print(r_tools.render_multi_edit_tool_call(e.arguments))
            case tools.BASH:
                self.print(r_tools.render_generic_tool_call(e.tool_name, e.arguments, ">"))
            case tools.APPLY_PATCH:
                self.print(r_tools.render_apply_patch_tool_call(e.arguments))
            case tools.TODO_WRITE:
                self.print(r_tools.render_generic_tool_call("Update Todos", "", "▪︎"))
            case tools.UPDATE_PLAN:
                self.print(r_tools.render_update_plan_tool_call(e.arguments))
            case tools.EXIT_PLAN_MODE:
                self.print(
                    r_tools.render_plan(e.arguments, box_style=self.box_style(), code_theme=self.themes.code_theme)
                )
            case tools.TASK | tools.ORACLE:
                color = self.pick_sub_agent_color(sub_agent_type=tools.SubAgentType(e.tool_name)).color
                self.print(r_tools.render_task_call(e, color))
            case _:
                self.print(r_tools.render_generic_tool_call(e.tool_name, e.arguments))

    def display_tool_call_result(self, e: events.ToolResultEvent) -> None:
        if e.status == "error" and not e.ui_extra:
            self.print(r_errors.render_error(Text(truncate_display(e.result))))
            return

        match e.tool_name:
            case tools.READ:
                pass
            case tools.EDIT | tools.MULTI_EDIT:
                self.print(Padding.indent(r_diffs.render_diff(e.ui_extra or ""), level=2))
            case tools.TODO_WRITE | tools.UPDATE_PLAN:
                self.print(r_tools.render_todo(e))
            case tools.EXIT_PLAN_MODE:
                self.print(r_tools.render_exit_plan_result(e.status, e.ui_extra))
            case tools.TASK | tools.ORACLE:
                self.print(
                    r_tools.render_task_result(
                        e, quote_style=self.get_sub_agent_color(), code_theme=self.themes.code_theme
                    )
                )
            case _:
                if e.tool_name in (tools.BASH, tools.APPLY_PATCH) and e.result.startswith("diff --git"):
                    self.print(r_diffs.render_diff_panel(e.result, show_file_name=True))
                    return
                if e.tool_name in (tools.BASH, tools.APPLY_PATCH) and e.ui_extra:
                    self.print(Padding.indent(r_diffs.render_diff(e.ui_extra, show_file_name=True), level=2))
                    return
                if len(e.result.strip()) == 0:
                    e.result = "(no content)"
                self.print(r_tools.render_generic_tool_result(e.result))

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        for event in history_events.events:
            match event:
                case events.TurnStartEvent():
                    self.print()
                case events.AssistantMessageEvent() as assistant_event:
                    if len(assistant_event.content.strip()) > 0:
                        self.print(
                            NoInsetMarkdown(
                                assistant_event.content.strip(),
                                code_theme=self.themes.code_theme,
                            )
                        )
                        self.print()
                    if assistant_event.annotations:
                        self.print(r_annotations.render_annotations(assistant_event.annotations))
                case events.ThinkingEvent() as thinking_event:
                    if len(thinking_event.content.strip()) > 0:
                        self.print(r_thinking.thinking_prefix())
                        self.print(
                            NoInsetMarkdown(
                                thinking_event.content.rstrip(),
                                code_theme=self.themes.code_theme,
                                style=self.console.get_style(ThemeKey.THINKING),
                            )
                        )
                        self.print()
                case events.DeveloperMessageEvent() as developer_event:
                    self.display_developer_message(developer_event)
                    self.display_command_output(developer_event)
                case events.UserMessageEvent() as user_event:
                    self.print(r_user_input.render_user_input(user_event.content))
                case events.ToolCallEvent() as tool_call_event:
                    tool_call_dict[tool_call_event.tool_call_id] = tool_call_event
                case events.ToolResultEvent() as tool_result_event:
                    tool_call_event = tool_call_dict.get(tool_result_event.tool_call_id)
                    if tool_call_event is not None:
                        self.display_tool_call(tool_call_event)
                    tool_call_dict.pop(tool_result_event.tool_call_id, None)
                    self.display_tool_call_result(tool_result_event)
                case events.ResponseMetadataEvent() as metadata_event:
                    self.print(r_metadata.render_response_metadata(metadata_event))
                    self.print()
                case events.InterruptEvent():
                    self.print()
                    self.print(r_user_input.render_interrupt())

    def display_developer_message(self, e: events.DeveloperMessageEvent) -> None:
        if not e.item.memory_paths and not e.item.external_file_changes and not e.item.todo_use and not e.item.at_files:
            return
        with self.session_print_context(e.session_id):
            self.print(r_developer.render_developer_message(e))

    def display_command_output(self, e: events.DeveloperMessageEvent) -> None:
        if not e.item.command_output:
            return
        with self.session_print_context(e.session_id):
            self.print(r_developer.render_command_output(e))
            self.print()
