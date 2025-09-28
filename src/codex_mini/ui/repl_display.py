import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator, Literal, override

from rich import box
from rich.box import Box
from rich.console import Console
from rich.padding import Padding
from rich.status import Status
from rich.style import Style, StyleType
from rich.text import Text

from codex_mini.protocol import events, tools
from codex_mini.ui.debouncer import Debouncer
from codex_mini.ui.display_abc import DisplayABC
from codex_mini.ui.mdstream import MarkdownStream, NoInsetMarkdown
from codex_mini.ui.osc94_progress_bar import OSC94States, emit_osc94
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
from codex_mini.ui.utils import remove_leading_newlines


@dataclass
class SessionStatus:
    is_subagent: bool = False
    color: Style | None = None
    sub_agent_type: tools.SubAgentType | None = None


class REPLDisplay(DisplayABC):
    def __init__(self, theme: str | None = None):
        self.themes = get_theme(theme)
        self.console: Console = Console(theme=self.themes.app_theme)
        self.console.push_theme(self.themes.markdown_theme)
        self.term_program = os.environ.get("TERM_PROGRAM", "").lower()
        self.spinner: Status = self.console.status(
            r_status.render_status_text("Thinking …", ThemeKey.SPINNER_STATUS_BOLD),
            spinner=r_status.spinner_name(),
            spinner_style=ThemeKey.SPINNER_STATUS,
        )

        self.stage: Literal["waiting", "thinking", "assistant", "tool_call", "tool_result"] = "waiting"
        self.is_thinking_in_bold = False

        self.assistant_mdstream: MarkdownStream | None = None
        self.accumulated_assistant_text = ""  # Not support parallel assistant delta yet
        self.assistant_debouncer = Debouncer(interval=1 / 20, callback=self._flush_assistant_buffer)

        self.accumulated_thinking_text = ""  # Not support parallel thinking delta yet
        self.thinking_debouncer = Debouncer(interval=1 / 20, callback=self._flush_thinking_buffer)

        self.session_map: dict[str, SessionStatus] = {}
        self.current_session_status: SessionStatus | None = None
        # Start at -1 so the first pick uses index 0
        self.subagent_color_index = -1
        self.subagent_color: Style = self.pick_sub_agent_color()

    @override
    async def consume_event(self, event: events.Event) -> None:
        match event:
            case events.ReplayHistoryEvent() as e:
                await self.replay_history(e)
                self.spinner.stop()
            case events.WelcomeEvent() as e:
                self.print(
                    r_metadata.render_welcome(e, box_style=self.box_style()),
                )
            case events.UserMessageEvent() as e:
                self.print(r_user_input.render_user_input(e.content))
            case events.TaskStartEvent() as e:
                self.spinner.start()
                self.session_map[e.session_id] = SessionStatus(
                    is_subagent=e.is_sub_agent,
                    color=self.get_sub_agent_color() if e.is_sub_agent else None,
                    sub_agent_type=e.sub_agent_type,
                )
                emit_osc94(OSC94States.INDETERMINATE)
            case events.DeveloperMessageEvent() as e:
                self.display_developer_message(e)
                self.display_command_output(e)
            case events.TurnStartEvent() as e:
                emit_osc94(OSC94States.INDETERMINATE)
                with self.session_print_context(e.session_id):
                    self.print()
            case events.ThinkingDeltaEvent() as e:
                if (
                    self.is_sub_agent_session(e.session_id)
                    and self.session_map[e.session_id].sub_agent_type != tools.ORACLE
                ):
                    return
                self.spinner.stop()
                if len(e.content.strip()) == 0 and self.stage != "thinking":
                    # Filter leading empty delta events
                    return
                if len(self.accumulated_thinking_text) == 0 and self.stage != "thinking":
                    # Filter leading multiple newlines
                    self.accumulated_thinking_text += remove_leading_newlines(e.content)
                else:
                    self.accumulated_thinking_text += e.content
                self.thinking_debouncer.schedule()
            case events.ThinkingEvent() as e:
                if (
                    self.is_sub_agent_session(e.session_id)
                    and self.session_map[e.session_id].sub_agent_type != tools.ORACLE
                ):
                    return
                self.thinking_debouncer.cancel()
                await self._flush_thinking_buffer()
                self.print("\n")
                self.is_thinking_in_bold = False
                self.spinner.start()
            case events.AssistantMessageDeltaEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                if len(e.content.strip()) == 0 and self.stage != "assistant":
                    # Filter leading empty delta events
                    return
                self.spinner.stop()
                self.accumulated_assistant_text += e.content
                if self.assistant_mdstream is None:
                    self.assistant_mdstream = MarkdownStream(
                        mdargs={"code_theme": self.themes.code_theme},
                        theme=self.themes.markdown_theme,
                        console=self.console,
                        spinner=self.spinner.renderable,
                    )
                    self.stage = "assistant"
                self.assistant_debouncer.schedule()
            case events.AssistantMessageEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                if self.assistant_mdstream is not None:
                    self.assistant_debouncer.cancel()
                    self.assistant_mdstream.update(e.content.strip(), final=True)
                else:
                    # Fallback for non-streamed assistant messages
                    content = e.content.strip()
                    if content:
                        self.print(
                            NoInsetMarkdown(
                                content,
                                code_theme=self.themes.code_theme,
                            )
                        )
                        self.print()
                self.accumulated_assistant_text = ""
                self.assistant_mdstream = None
                if e.annotations:
                    self.print(r_annotations.render_annotations(e.annotations))
                self.spinner.start()
            case events.TurnToolCallStartEvent() as e:
                pass
            case events.ToolCallEvent() as e:
                self.finish_assistant_stream()
                with self.session_print_context(e.session_id):
                    self.display_tool_call(e)
                self.stage = "tool_call"
            case events.ToolResultEvent() as e:
                if self.is_sub_agent_session(e.session_id):
                    return
                self.spinner.stop()
                self.display_tool_call_result(e)
                self.stage = "tool_result"
                self.spinner.start()
            case events.ResponseMetadataEvent() as e:
                with self.session_print_context(e.session_id):
                    self.print(r_metadata.render_response_metadata(e))
                    self.print()
            case events.TodoChangeEvent() as e:
                active_form_status_text = ""
                for todo in e.todos:
                    if todo.status == "in_progress":
                        if len(todo.activeForm) > 0:
                            active_form_status_text = todo.activeForm
                            break
                        elif len(todo.content) > 0:
                            active_form_status_text = todo.content
                            break
                if len(active_form_status_text) > 0:
                    self.spinner.update(
                        r_status.render_status_text(active_form_status_text, ThemeKey.SPINNER_STATUS_BOLD)
                    )
                else:
                    self.spinner.update(r_status.render_status_text("Thinking …", ThemeKey.SPINNER_STATUS_BOLD))
            case events.TurnEndEvent():
                pass
            case events.TaskFinishEvent():
                self.spinner.stop()
                self.finish_assistant_stream()
                emit_osc94(OSC94States.HIDDEN)
            case events.InterruptEvent() as e:
                self.spinner.stop()
                self.finish_assistant_stream()
                emit_osc94(OSC94States.HIDDEN)
                self.print(r_user_input.render_interrupt())
            case events.ErrorEvent() as e:
                emit_osc94(OSC94States.HIDDEN)
                self.print(r_errors.render_error(self.console.render_str(truncate_display(e.error_message))))
                self.print()
                self.spinner.stop()
            case events.EndEvent():
                emit_osc94(OSC94States.HIDDEN)
                self.spinner.stop()
            # case _:
            #     self.print("[Event]", event.__class__.__name__, event)

    @override
    async def start(self) -> None:
        pass

    @override
    async def stop(self) -> None:
        await self.assistant_debouncer.flush()
        await self.thinking_debouncer.flush()
        self.assistant_debouncer.cancel()
        self.thinking_debouncer.cancel()
        pass

    def finish_assistant_stream(self):
        if self.assistant_mdstream is not None:
            self.assistant_debouncer.cancel()
            self.assistant_mdstream.update(self.accumulated_assistant_text, final=True)
            self.assistant_mdstream = None
            self.accumulated_assistant_text = ""

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
        if self.term_program == "warpterminal":
            return box.SQUARE
        return box.ROUNDED

    @contextmanager
    def session_print_context(self, session_id: str) -> Iterator[None]:
        """Context manager for subagent QuoteStyle"""
        old = self.current_session_status
        if session_id in self.session_map:
            # For sub-agent
            self.current_session_status = self.session_map[session_id]
        try:
            yield
        finally:
            self.current_session_status = old

    def print(self, *objects: Any, style: StyleType | None = None, end: str = "\n"):
        if (
            self.current_session_status
            and self.current_session_status.is_subagent
            and self.current_session_status.color
        ):
            # If it's sub-agent
            if objects:
                self.console.print(Quote(*objects, style=self.current_session_status.color))
            else:
                self.console.print(Quote("", style=self.current_session_status.color))
        else:
            self.console.print(*objects, style=style, end=end)

    async def _flush_assistant_buffer(self) -> None:
        """Flush assistant buffer"""
        if self.assistant_mdstream is not None:
            # Do not strip here; stripping can cause transient shrink of text,
            # which breaks the stable/live window split and leads to duplicates.
            self.assistant_mdstream.update(self.accumulated_assistant_text)

    async def _flush_thinking_buffer(self) -> None:
        """Flush thinking buffer"""
        content = self.accumulated_thinking_text.replace("\r", "")
        if len(content.strip()) == 0:
            self.accumulated_thinking_text = ""
            return
        self._render_thinking_content(content)
        self.accumulated_thinking_text = ""

    def _render_thinking_content(self, content: str) -> None:
        """
        Handle markdown bold syntax in thinking text.
        """
        if self.stage != "thinking":
            self.print(r_thinking.thinking_prefix())
            self.stage = "thinking"
        self.print(r_thinking.render_thinking_content(content, self.is_thinking_in_bold), end="")
        # Toggle bold state when an odd number of '**' markers are seen
        if content.count("**") % 2 == 1:
            self.is_thinking_in_bold = not self.is_thinking_in_bold

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
            case tools.SHELL:
                self.print(r_tools.render_shell_tool_call(e.arguments))
            case tools.TODO_WRITE:
                self.print(r_tools.render_generic_tool_call("Update Todos", "", "▪︎"))
            case tools.UPDATE_PLAN:
                self.print(r_tools.render_update_plan_tool_call(e.arguments))
            case tools.EXIT_PLAN_MODE:
                self.print(
                    r_tools.render_plan(e.arguments, box_style=self.box_style(), code_theme=self.themes.code_theme)
                )
            case tools.TASK | tools.ORACLE:
                # Display parent session's Task tool call before sub-agent session's TaskStartEvent arrives. Since session ID is unavailable here, pick a new subagent color here instead of consuming TaskStartEvent
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
                # Not display read tool result
                pass
            case tools.EDIT | tools.MULTI_EDIT:
                self.print(
                    Padding.indent(
                        r_diffs.render_diff(e.ui_extra or ""),
                        level=2,
                    )
                )
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
                # handle bash `git diff`
                if e.tool_name in (tools.BASH, tools.SHELL) and e.result.startswith("diff --git"):
                    self.print(r_diffs.render_diff_panel(e.result, show_file_name=True))
                    return

                if e.tool_name in (tools.BASH, tools.SHELL) and e.ui_extra:
                    # apply_patch diff result
                    self.print(
                        Padding.indent(
                            r_diffs.render_diff(e.ui_extra, show_file_name=True),
                            level=2,
                        )
                    )
                    return

                if len(e.result.strip()) == 0:
                    e.result = "(no content)"
                self.print(r_tools.render_generic_tool_result(e.result))

    def display_user_input(self, e: events.UserMessageEvent) -> None:
        self.print(r_user_input.render_user_input(e.content))

    async def replay_history(self, history_events: events.ReplayHistoryEvent) -> None:
        if history_events.is_load:
            self.print()
            self.print(r_metadata.render_resume_loading())
        self.print()
        tool_call_dict: dict[str, events.ToolCallEvent] = {}
        for event in history_events.events:
            match event:
                case events.TurnStartEvent() as e:
                    self.print()
                case events.AssistantMessageEvent() as e:
                    if len(e.content.strip()) > 0:
                        self.print(
                            NoInsetMarkdown(
                                e.content.strip(),
                                code_theme=self.themes.code_theme,
                            )
                        )
                        self.print()
                    if e.annotations:
                        self.print(r_annotations.render_annotations(e.annotations))
                case events.ThinkingEvent() as e:
                    if len(e.content.strip()) > 0:
                        self.print(r_thinking.thinking_prefix())
                        self.print(
                            NoInsetMarkdown(
                                e.content.rstrip(),
                                code_theme=self.themes.code_theme,
                                style=self.console.get_style(ThemeKey.THINKING),
                            )
                        )
                        self.print()
                case events.DeveloperMessageEvent() as e:
                    self.display_developer_message(e)
                    self.display_command_output(e)
                case events.UserMessageEvent() as e:
                    self.print()
                    self.print(r_user_input.render_user_input(e.content))
                case events.ToolCallEvent() as e:
                    tool_call_dict[e.tool_call_id] = e
                case events.ToolResultEvent() as e:
                    tool_call_event = tool_call_dict.get(e.tool_call_id)
                    if tool_call_event is not None:
                        self.display_tool_call(tool_call_event)
                    tool_call_dict.pop(e.tool_call_id, None)
                    # TODO: Replay Sub-Agent Events
                    self.display_tool_call_result(e)
                case events.ResponseMetadataEvent() as e:
                    self.print(r_metadata.render_response_metadata(e))
                    self.print()
                case events.InterruptEvent() as e:
                    self.print(r_user_input.render_interrupt())
        if history_events.is_load:
            self.print()
            self.print(r_metadata.render_resume_loaded(history_events.updated_at))
        self.print()

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
