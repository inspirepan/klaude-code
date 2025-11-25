from __future__ import annotations

import json
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

from klaude_code.core.sub_agent import get_sub_agent_profile_by_tool
from klaude_code.protocol import events, model, tools
from klaude_code.ui.base.theme import ThemeKey, get_theme
from klaude_code.ui.renderers import developer as r_developer
from klaude_code.ui.renderers import diffs as r_diffs
from klaude_code.ui.renderers import errors as r_errors
from klaude_code.ui.renderers import metadata as r_metadata
from klaude_code.ui.renderers import status as r_status
from klaude_code.ui.renderers import sub_agent as r_sub_agent
from klaude_code.ui.renderers import tools as r_tools
from klaude_code.ui.renderers import user_input as r_user_input
from klaude_code.ui.renderers.common import create_grid, truncate_display
from klaude_code.ui.rich_ext.markdown import NoInsetMarkdown
from klaude_code.ui.rich_ext.quote import Quote


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
        self.spinner: Status = self.console.status(
            r_status.render_status_text("Thinking …", ThemeKey.SPINNER_STATUS_TEXT),
            spinner=r_status.spinner_name(),
            spinner_style=ThemeKey.SPINNER_STATUS,
        )

        self.session_map: dict[str, SessionStatus] = {}
        self.current_sub_agent_color: Style | None = None
        self.subagent_color_index = 0

    def register_session(self, session_id: str, status: SessionStatus) -> None:
        self.session_map[session_id] = status

    def is_sub_agent_session(self, session_id: str) -> bool:
        return session_id in self.session_map and self.session_map[session_id].sub_agent_state is not None

    def _advance_sub_agent_color_index(self) -> None:
        palette_size = len(self.themes.sub_agent_colors)
        if palette_size == 0:
            self.subagent_color_index = 0
            return
        self.subagent_color_index = (self.subagent_color_index + 1) % palette_size

    def pick_sub_agent_color(self) -> Style:
        self._advance_sub_agent_color_index()
        palette = self.themes.sub_agent_colors
        if not palette:
            return Style()
        return palette[self.subagent_color_index]

    def get_sub_agent_color(self, session_id: str) -> Style:
        status = self.session_map.get(session_id)
        if status and status.color:
            return status.color
        return Style()

    def box_style(self) -> Box:
        return box.ROUNDED

    @staticmethod
    def _extract_diff_text(ui_extra: model.ToolResultUIExtra | None) -> str | None:
        if ui_extra is None:
            return None
        if ui_extra.type == model.ToolResultUIExtraType.DIFF_TEXT:
            return ui_extra.diff_text
        return None

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
                self.console.print(Quote(*objects, style=self.current_sub_agent_color))
            return
        self.console.print(*objects, style=style, end=end)

    def display_tool_call(self, e: events.ToolCallEvent) -> None:
        if r_tools.is_sub_agent_tool(e.tool_name):
            # In replay mode, render sub-agent call here
            # In normal execution, handled by TaskStartEvent
            if e.is_replay:
                state = self._build_sub_agent_state_from_tool_call(e)
                if state is not None:
                    self.print(r_sub_agent.render_sub_agent_call(state))
            return
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
                self.print(r_tools.render_generic_tool_call("Update Todos", "", "◎"))
            case tools.UPDATE_PLAN:
                self.print(r_tools.render_update_plan_tool_call(e.arguments))
            case tools.MERMAID:
                self.print(r_tools.render_mermaid_tool_call(e.arguments))
            case tools.SKILL:
                self.print(r_tools.render_generic_tool_call(e.tool_name, e.arguments, "◈"))
            case _:
                self.print(r_tools.render_generic_tool_call(e.tool_name, e.arguments))

    def display_tool_call_result(self, e: events.ToolResultEvent) -> None:
        if r_tools.is_sub_agent_tool(e.tool_name):
            # In replay mode, render sub-agent result here
            # In normal execution, handled by TaskFinishEvent
            if e.is_replay:
                self.print(r_sub_agent.render_sub_agent_result(e.result, code_theme=self.themes.code_theme))
            return
        if e.status == "error" and e.ui_extra is None:
            self.print(r_errors.render_error(Text(truncate_display(e.result))))
            return

        diff_text = self._extract_diff_text(e.ui_extra)

        match e.tool_name:
            case tools.READ:
                pass
            case tools.EDIT | tools.MULTI_EDIT:
                self.print(Padding.indent(r_diffs.render_diff(diff_text or ""), level=2))
            case tools.TODO_WRITE | tools.UPDATE_PLAN:
                self.print(r_tools.render_todo(e))
            case tools.MERMAID:
                self.print(r_tools.render_mermaid_tool_result(e))
            case _:
                if e.tool_name in (tools.BASH, tools.APPLY_PATCH) and e.result.startswith("diff --git"):
                    self.print(r_diffs.render_diff_panel(e.result, show_file_name=True))
                    return
                if e.tool_name == tools.APPLY_PATCH and diff_text:
                    self.print(Padding.indent(r_diffs.render_diff(diff_text, show_file_name=True), level=2))
                    return
                if len(e.result.strip()) == 0:
                    e.result = "(no content)"
                self.print(r_tools.render_generic_tool_result(e.result))

    def _build_sub_agent_state_from_tool_call(self, e: events.ToolCallEvent) -> model.SubAgentState | None:
        profile = get_sub_agent_profile_by_tool(e.tool_name)
        if profile is None:
            return None
        description = profile.name
        prompt = ""
        if e.arguments:
            try:
                payload: dict[str, object] = json.loads(e.arguments)
            except json.JSONDecodeError:
                payload = {}
            desc_value = payload.get("description")
            if isinstance(desc_value, str) and desc_value.strip():
                description = desc_value.strip()
            prompt_value = payload.get("prompt") or payload.get("task")
            if isinstance(prompt_value, str):
                prompt = prompt_value.strip()
        return model.SubAgentState(
            sub_agent_type=profile.name,
            sub_agent_desc=description,
            sub_agent_prompt=prompt,
        )

    def display_thinking(self, content: str) -> None:
        if len(content.strip()) > 0:
            self.console.push_theme(theme=self.themes.thinking_markdown_theme)
            self.print(
                Padding.indent(
                    NoInsetMarkdown(
                        content.rstrip()
                        .replace("**\n\n", "**  \n")
                        .replace("****", "**\n\n**"),  # remove extra newlines after bold titles
                        code_theme=self.themes.code_theme,
                        style=self.console.get_style(ThemeKey.THINKING),
                    ),
                    level=2,
                )
            )
            self.console.pop_theme()
            self.print()

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        for event in history_events.events:
            match event:
                case events.TurnStartEvent():
                    self.print()
                case events.AssistantMessageEvent() as assistant_event:
                    if len(assistant_event.content.strip()) > 0:
                        grid = create_grid()
                        grid.add_row(
                            "•",
                            NoInsetMarkdown(
                                assistant_event.content.strip(),
                                code_theme=self.themes.code_theme,
                            ),
                        )
                        self.print(grid)
                        self.print()
                case events.ThinkingEvent() as thinking_event:
                    self.display_thinking(thinking_event.content)
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
