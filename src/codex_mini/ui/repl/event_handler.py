from __future__ import annotations

from typing import Awaitable, Callable

from codex_mini.protocol import events
from codex_mini.ui.base.debouncer import Debouncer
from codex_mini.ui.base.osc94_progress_bar import OSC94States, emit_osc94
from codex_mini.ui.base.stage_manager import Stage, StageManager
from codex_mini.ui.base.theme import ThemeKey
from codex_mini.ui.renderers import errors as r_errors
from codex_mini.ui.renderers import metadata as r_metadata
from codex_mini.ui.renderers import status as r_status
from codex_mini.ui.renderers import thinking as r_thinking
from codex_mini.ui.renderers import user_input as r_user_input
from codex_mini.ui.renderers.common import truncate_display
from codex_mini.ui.repl.renderer import REPLRenderer, SessionStatus
from codex_mini.ui.rich_ext.markdown import MarkdownStream, NoInsetMarkdown


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


class DisplayEventHandler:
    """Handle REPL events, buffering and delegating rendering work."""

    def __init__(self, renderer: REPLRenderer):
        self.renderer = renderer
        self.assistant_stream = StreamState(interval=1 / 20, flush_handler=self._flush_assistant_buffer)

        self.stage_manager = StageManager(
            finish_assistant=self.finish_assistant_stream,
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
                        color=self.renderer.get_sub_agent_color()
                        if task_event.is_sub_agent
                        else None,  # sub agent color should be advanced in tool call display, not here
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
            case events.ThinkingEvent() as thinking_event:
                if self._should_suppress_subagent_thinking(thinking_event.session_id):
                    return
                await self.stage_manager.enter_thinking_stage()
                # self.renderer.spinner.stop()
                with self.renderer.session_print_context(thinking_event.session_id):
                    self.renderer.display_thinking(thinking_event.content)
                # self.renderer.spinner.start()
            case events.AssistantMessageDeltaEvent() as assistant_delta:
                if self.renderer.is_sub_agent_session(assistant_delta.session_id):
                    return
                if len(assistant_delta.content.strip()) == 0 and self.stage_manager.current_stage != Stage.ASSISTANT:
                    return
                self.renderer.spinner.stop()
                await self.stage_manager.transition_to(Stage.ASSISTANT)
                self.assistant_stream.append(assistant_delta.content)
                if self.assistant_stream.mdstream is None:
                    self.assistant_stream.mdstream = MarkdownStream(
                        mdargs={"code_theme": self.renderer.themes.code_theme},
                        theme=self.renderer.themes.markdown_theme,
                        console=self.renderer.console,
                        spinner=self.renderer.spinner.renderable,
                    )
                self.assistant_stream.debouncer.schedule()
            case events.AssistantMessageEvent() as assistant_event:
                if self.renderer.is_sub_agent_session(assistant_event.session_id):
                    return
                await self.stage_manager.transition_to(Stage.ASSISTANT)
                if self.assistant_stream.mdstream is not None:
                    self.assistant_stream.debouncer.cancel()
                    self.assistant_stream.mdstream.update(assistant_event.content.strip(), final=True)
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
                self.assistant_stream.clear()
                self.assistant_stream.mdstream = None
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
        await self.assistant_stream.debouncer.flush()
        self.assistant_stream.debouncer.cancel()

    async def finish_assistant_stream(self) -> None:
        if self.assistant_stream.mdstream is not None:
            self.assistant_stream.debouncer.cancel()
            self.assistant_stream.mdstream.update(self.assistant_stream.buffer, final=True)
            self.assistant_stream.mdstream = None
            self.assistant_stream.clear()

    def _print_thinking_prefix(self) -> None:
        self.renderer.print(r_thinking.thinking_prefix())

    async def _flush_assistant_buffer(self, state: StreamState) -> None:
        if state.mdstream is not None:
            state.mdstream.update(state.buffer)

    def _should_suppress_subagent_thinking(self, session_id: str) -> bool:
        return self.renderer.is_sub_agent_session(session_id)

    def _extract_active_form_text(self, todo_event: events.TodoChangeEvent) -> str:
        for todo in todo_event.todos:
            if todo.status == "in_progress":
                if len(todo.activeForm) > 0:
                    return todo.activeForm
                if len(todo.content) > 0:
                    return todo.content
        return ""
