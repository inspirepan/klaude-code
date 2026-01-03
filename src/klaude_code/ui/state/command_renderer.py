from __future__ import annotations

import contextlib
from collections.abc import Callable
from dataclasses import dataclass

from rich.rule import Rule

from klaude_code.const import MARKDOWN_LEFT_MARGIN, MARKDOWN_STREAM_LIVE_REPAINT_ENABLED
from klaude_code.ui.modes.repl.renderer import REPLRenderer
from klaude_code.ui.renderers.assistant import ASSISTANT_MESSAGE_MARK
from klaude_code.ui.renderers.thinking import THINKING_MESSAGE_MARK, normalize_thinking_content
from klaude_code.ui.rich import status as r_status
from klaude_code.ui.rich.markdown import MarkdownStream, ThinkingMarkdown
from klaude_code.ui.rich.theme import ThemeKey
from klaude_code.ui.state.render_command import (
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
from klaude_code.ui.terminal.notifier import (
    Notification,
    NotificationType,
    TerminalNotifier,
    emit_tmux_signal,
)
from klaude_code.ui.terminal.progress_bar import OSC94States, emit_osc94


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


class CommandRenderer:
    """Execute RenderCommand sequences against the REPL renderer.

    This is the only component that performs actual terminal rendering.
    """

    def __init__(self, renderer: REPLRenderer, notifier: TerminalNotifier | None = None) -> None:
        self._renderer = renderer
        self._notifier = notifier
        self._assistant_stream = _StreamState()
        self._thinking_stream = _StreamState()

    def _maybe_notify_task_finish(self, event: RenderTaskFinish) -> None:
        if self._notifier is None:
            return
        if self._renderer.is_sub_agent_session(event.event.session_id):
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

    def _new_thinking_mdstream(self) -> MarkdownStream:
        return MarkdownStream(
            mdargs={
                "code_theme": self._renderer.themes.code_theme,
                "style": ThemeKey.THINKING,
            },
            theme=self._renderer.themes.thinking_markdown_theme,
            console=self._renderer.console,
            live_sink=self._renderer.set_stream_renderable if MARKDOWN_STREAM_LIVE_REPAINT_ENABLED else None,
            mark=THINKING_MESSAGE_MARK,
            mark_style=ThemeKey.THINKING,
            left_margin=MARKDOWN_LEFT_MARGIN,
            markdown_class=ThinkingMarkdown,
        )

    def _new_assistant_mdstream(self) -> MarkdownStream:
        return MarkdownStream(
            mdargs={"code_theme": self._renderer.themes.code_theme},
            theme=self._renderer.themes.markdown_theme,
            console=self._renderer.console,
            live_sink=self._renderer.set_stream_renderable if MARKDOWN_STREAM_LIVE_REPAINT_ENABLED else None,
            mark=ASSISTANT_MESSAGE_MARK,
            left_margin=MARKDOWN_LEFT_MARGIN,
        )

    def _flush_thinking(self) -> None:
        self._thinking_stream.render(transform=normalize_thinking_content)

    def _flush_assistant(self) -> None:
        self._assistant_stream.render()

    async def execute(self, commands: list[RenderCommand]) -> None:
        for cmd in commands:
            match cmd:
                case RenderReplayHistory(event=event):
                    await self._renderer.replay_history(event)
                    self._renderer.spinner_stop()
                case RenderWelcome(event=event):
                    self._renderer.display_welcome(event)
                case RenderUserMessage(event=event):
                    self._renderer.display_user_message(event)
                case RenderTaskStart(event=event):
                    self._renderer.display_task_start(event)
                case RenderDeveloperMessage(event=event):
                    self._renderer.display_developer_message(event)
                    self._renderer.display_command_output(event)
                case RenderTurnStart(event=event):
                    self._renderer.display_turn_start(event)
                case StartThinkingStream():
                    if not self._thinking_stream.is_active:
                        self._thinking_stream.start(self._new_thinking_mdstream())
                case AppendThinking(content=content):
                    if self._thinking_stream.is_active:
                        first_delta = self._thinking_stream.buffer == ""
                        self._thinking_stream.append(content)
                        if first_delta:
                            self._thinking_stream.render(transform=normalize_thinking_content)
                        self._flush_thinking()
                case EndThinkingStream():
                    finalized = self._thinking_stream.finalize(transform=normalize_thinking_content)
                    if finalized:
                        self._renderer.print()
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
                        self._renderer.print()
                case RenderThinkingHeader(session_id=session_id, header=header):
                    with self._renderer.session_print_context(session_id):
                        self._renderer.display_thinking_header(header)
                case RenderAssistantImage(file_path=file_path):
                    self._renderer.display_image(file_path)
                case RenderToolCall(event=event):
                    with self._renderer.session_print_context(event.session_id):
                        self._renderer.display_tool_call(event)
                case RenderToolResult(event=event, is_sub_agent_session=is_sub_agent_session):
                    with self._renderer.session_print_context(event.session_id):
                        self._renderer.display_tool_call_result(event, is_sub_agent=is_sub_agent_session)
                case RenderTaskMetadata(event=event):
                    self._renderer.display_task_metadata(event)
                case RenderTaskFinish() as cmd:
                    self._renderer.display_task_finish(cmd.event)
                    self._maybe_notify_task_finish(cmd)
                case RenderInterrupt():
                    self._renderer.display_interrupt()
                case RenderError(event=event):
                    self._renderer.display_error(event)
                case SpinnerStart():
                    self._renderer.spinner_start()
                case SpinnerStop():
                    self._renderer.spinner_stop()
                case SpinnerUpdate(status_text=status_text, right_text=right_text):
                    self._renderer.spinner_update(status_text, right_text)
                case PrintBlankLine():
                    self._renderer.print()
                case PrintRuleLine():
                    self._renderer.console.print(Rule(characters="─", style=ThemeKey.LINES))
                case EmitOsc94Error():
                    emit_osc94(OSC94States.ERROR)
                case EmitTmuxSignal():
                    emit_tmux_signal()
                case TaskClockStart():
                    r_status.set_task_start()
                case TaskClockClear():
                    r_status.clear_task_start()
                case _:
                    # Defensive: ignore unknown command types.
                    continue

    async def stop(self) -> None:
        self._flush_assistant()
        self._flush_thinking()
        with contextlib.suppress(Exception):
            self._renderer.spinner_stop()
