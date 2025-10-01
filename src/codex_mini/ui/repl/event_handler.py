from __future__ import annotations

from codex_mini.protocol import events, tools
from codex_mini.ui.base.debouncer import Debouncer
from codex_mini.ui.rich_ext.markdown import MarkdownStream, NoInsetMarkdown
from codex_mini.ui.base.osc94_progress_bar import OSC94States, emit_osc94
from codex_mini.ui.renderers import annotations as r_annotations
from codex_mini.ui.renderers import errors as r_errors
from codex_mini.ui.renderers import metadata as r_metadata
from codex_mini.ui.renderers import status as r_status
from codex_mini.ui.renderers import thinking as r_thinking
from codex_mini.ui.renderers import user_input as r_user_input
from codex_mini.ui.renderers.common import truncate_display
from codex_mini.ui.repl.renderer import REPLRenderer, SessionStatus
from codex_mini.ui.base.stage_manager import Stage, StageManager
from codex_mini.ui.base.theme import ThemeKey
from codex_mini.ui.base.utils import remove_leading_newlines


class DisplayEventHandler:
    """Handle REPL events, buffering and delegating rendering work."""

    def __init__(self, renderer: REPLRenderer):
        self.renderer = renderer
        self.assistant_mdstream: MarkdownStream | None = None
        self.accumulated_assistant_text = ""
        self.assistant_debouncer = Debouncer(interval=1 / 20, callback=self._flush_assistant_buffer)

        self.accumulated_thinking_text = ""
        self.thinking_debouncer = Debouncer(interval=1 / 20, callback=self._flush_thinking_buffer)
        self.is_thinking_in_bold = False

        self.stage_manager = StageManager(
            finish_assistant=self.finish_assistant_stream,
            finish_thinking=self.finish_thinking_stream,
            on_enter_thinking=self._print_thinking_prefix,
        )

    async def consume_event(self, event: events.Event) -> None:
        match event:
            case events.ReplayHistoryEvent() as replay_event:
                await self.renderer.replay_history(replay_event)
                self.renderer.spinner.stop()
            case events.WelcomeEvent() as welcome_event:
                self.renderer.print(r_metadata.render_welcome(welcome_event, box_style=self.renderer.box_style()))
            case events.UserMessageEvent() as user_event:
                self.renderer.print(r_user_input.render_user_input(user_event.content))
            case events.TaskStartEvent() as task_event:
                self.renderer.spinner.start()
                self.renderer.register_session(
                    task_event.session_id,
                    SessionStatus(
                        is_subagent=task_event.is_sub_agent,
                        color=self.renderer.get_sub_agent_color() if task_event.is_sub_agent else None,
                        sub_agent_type=task_event.sub_agent_type,
                    ),
                )
                emit_osc94(OSC94States.INDETERMINATE)
            case events.DeveloperMessageEvent() as developer_event:
                self.renderer.display_developer_message(developer_event)
                self.renderer.display_command_output(developer_event)
            case events.TurnStartEvent() as turn_start_event:
                emit_osc94(OSC94States.INDETERMINATE)
                with self.renderer.session_print_context(turn_start_event.session_id):
                    self.renderer.print()
            case events.ThinkingDeltaEvent() as thinking_delta:
                if self._should_suppress_subagent_thinking(thinking_delta.session_id):
                    return
                self.renderer.spinner.stop()
                if len(thinking_delta.content.strip()) == 0 and self.stage_manager.current_stage != Stage.THINKING:
                    # Remove empty leading spaces
                    return
                if len(self.accumulated_thinking_text) == 0 and self.stage_manager.current_stage != Stage.THINKING:
                    # Remove leading newlines
                    self.accumulated_thinking_text += remove_leading_newlines(thinking_delta.content)
                else:
                    self.accumulated_thinking_text += thinking_delta.content
                await self.stage_manager.enter_thinking_stage()
                self.thinking_debouncer.schedule()
            case events.ThinkingEvent() as thinking_event:
                if self._should_suppress_subagent_thinking(thinking_event.session_id):
                    return
                if (
                    thinking_event.content
                    and self.stage_manager.current_stage == Stage.WAITING
                    and len(self.accumulated_thinking_text.strip()) == 0
                ):
                    self.accumulated_thinking_text += thinking_event.content
                await self.stage_manager.finish_thinking()
                self.renderer.spinner.start()
            case events.AssistantMessageDeltaEvent() as assistant_delta:
                if self.renderer.is_sub_agent_session(assistant_delta.session_id):
                    return
                if len(assistant_delta.content.strip()) == 0 and self.stage_manager.current_stage != Stage.ASSISTANT:
                    return
                self.renderer.spinner.stop()
                await self.stage_manager.transition_to(Stage.ASSISTANT)
                self.accumulated_assistant_text += assistant_delta.content
                if self.assistant_mdstream is None:
                    self.assistant_mdstream = MarkdownStream(
                        mdargs={"code_theme": self.renderer.themes.code_theme},
                        theme=self.renderer.themes.markdown_theme,
                        console=self.renderer.console,
                        spinner=self.renderer.spinner.renderable,
                    )
                self.assistant_debouncer.schedule()
            case events.AssistantMessageEvent() as assistant_event:
                if self.renderer.is_sub_agent_session(assistant_event.session_id):
                    return
                await self.stage_manager.transition_to(Stage.ASSISTANT)
                if self.assistant_mdstream is not None:
                    self.assistant_debouncer.cancel()
                    self.assistant_mdstream.update(assistant_event.content.strip(), final=True)
                else:
                    content = assistant_event.content.strip()
                    if content:
                        self.renderer.print(
                            NoInsetMarkdown(
                                content,
                                code_theme=self.renderer.themes.code_theme,
                            )
                        )
                        self.renderer.print()
                self.accumulated_assistant_text = ""
                self.assistant_mdstream = None
                if assistant_event.annotations:
                    self.renderer.print(r_annotations.render_annotations(assistant_event.annotations))
                await self.stage_manager.transition_to(Stage.WAITING)
                self.renderer.spinner.start()
            case events.TurnToolCallStartEvent():
                pass
            case events.ToolCallEvent() as tool_call_event:
                await self.stage_manager.transition_to(Stage.TOOL_CALL)
                with self.renderer.session_print_context(tool_call_event.session_id):
                    self.renderer.display_tool_call(tool_call_event)
            case events.ToolResultEvent() as tool_result_event:
                if self.renderer.is_sub_agent_session(tool_result_event.session_id):
                    return
                await self.stage_manager.transition_to(Stage.TOOL_RESULT)
                self.renderer.spinner.stop()
                self.renderer.display_tool_call_result(tool_result_event)
                self.renderer.spinner.start()
            case events.ResponseMetadataEvent() as metadata_event:
                with self.renderer.session_print_context(metadata_event.session_id):
                    self.renderer.print(r_metadata.render_response_metadata(metadata_event))
                    self.renderer.print()
            case events.TodoChangeEvent() as todo_event:
                active_form_status_text = self._extract_active_form_text(todo_event)
                if len(active_form_status_text) > 0:
                    self.renderer.spinner.update(
                        r_status.render_status_text(active_form_status_text, ThemeKey.SPINNER_STATUS_BOLD)
                    )
                else:
                    self.renderer.spinner.update(
                        r_status.render_status_text("Thinking …", ThemeKey.SPINNER_STATUS_BOLD)
                    )
            case events.TurnEndEvent():
                pass
            case events.TaskFinishEvent():
                self.renderer.spinner.stop()
                await self.stage_manager.transition_to(Stage.WAITING)
                emit_osc94(OSC94States.HIDDEN)
            case events.InterruptEvent():
                self.renderer.spinner.stop()
                await self.stage_manager.transition_to(Stage.WAITING)
                emit_osc94(OSC94States.HIDDEN)
                self.renderer.print(r_user_input.render_interrupt())
            case events.ErrorEvent() as error_event:
                emit_osc94(OSC94States.HIDDEN)
                await self.stage_manager.transition_to(Stage.WAITING)
                self.renderer.print(
                    r_errors.render_error(
                        self.renderer.console.render_str(truncate_display(error_event.error_message)),
                        indent=0,
                    )
                )
                self.renderer.spinner.stop()
            case events.EndEvent():
                emit_osc94(OSC94States.HIDDEN)
                await self.stage_manager.transition_to(Stage.WAITING)
                self.renderer.spinner.stop()

    async def stop(self) -> None:
        await self.assistant_debouncer.flush()
        await self.thinking_debouncer.flush()
        self.assistant_debouncer.cancel()
        self.thinking_debouncer.cancel()

    async def finish_assistant_stream(self) -> None:
        if self.assistant_mdstream is not None:
            self.assistant_debouncer.cancel()
            self.assistant_mdstream.update(self.accumulated_assistant_text, final=True)
            self.assistant_mdstream = None
            self.accumulated_assistant_text = ""

    async def finish_thinking_stream(self) -> None:
        self.thinking_debouncer.cancel()
        await self._flush_thinking_buffer()
        if self.stage_manager.current_stage == Stage.THINKING:
            self.renderer.print("\n")
        self.is_thinking_in_bold = False
        self.accumulated_thinking_text = ""

    def _print_thinking_prefix(self) -> None:
        self.renderer.print(r_thinking.thinking_prefix())

    async def _flush_assistant_buffer(self) -> None:
        if self.assistant_mdstream is not None:
            self.assistant_mdstream.update(self.accumulated_assistant_text)

    async def _flush_thinking_buffer(self) -> None:
        content = self.accumulated_thinking_text.replace("\r", "")
        if len(content.strip()) == 0:
            self.accumulated_thinking_text = ""
            return
        self._render_thinking_content(content)
        self.accumulated_thinking_text = ""

    def _render_thinking_content(self, content: str) -> None:
        if self.stage_manager.current_stage != Stage.THINKING:
            self._print_thinking_prefix()
        self.renderer.print(r_thinking.render_thinking_content(content, self.is_thinking_in_bold), end="")
        if content.count("**") % 2 == 1:
            self.is_thinking_in_bold = not self.is_thinking_in_bold

    def _should_suppress_subagent_thinking(self, session_id: str) -> bool:
        return (
            self.renderer.is_sub_agent_session(session_id)
            and self.renderer.session_map[session_id].sub_agent_type != tools.ORACLE
        )

    def _extract_active_form_text(self, todo_event: events.TodoChangeEvent) -> str:
        for todo in todo_event.todos:
            if todo.status == "in_progress":
                if len(todo.activeForm) > 0:
                    return todo.activeForm
                if len(todo.content) > 0:
                    return todo.content
        return ""
