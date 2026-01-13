from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from klaude_code.const import (
    SIGINT_DOUBLE_PRESS_EXIT_TEXT,
    STATUS_COMPACTING_TEXT,
    STATUS_COMPOSING_TEXT,
    STATUS_DEFAULT_TEXT,
    STATUS_RUNNING_TEXT,
    STATUS_SHOW_BUFFER_LENGTH,
    STATUS_THINKING_TEXT,
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
from klaude_code.tui.components.rich import status as r_status
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.thinking import extract_last_bold_header, normalize_thinking_content
from klaude_code.tui.components.tools import get_task_active_form, get_tool_active_form, is_sub_agent_tool

# Tools that complete quickly and don't benefit from streaming activity display.
# For models without fine-grained tool JSON streaming (e.g., Gemini), showing these
# in the activity state causes a flash-and-disappear effect.
FAST_TOOLS: frozenset[str] = frozenset(
    {
        tools.READ,
        tools.EDIT,
        tools.WRITE,
        tools.BASH,
        tools.TODO_WRITE,
        tools.UPDATE_PLAN,
        tools.APPLY_PATCH,
        tools.REPORT_BACK,
    }
)


class ActivityState:
    """Tracks composing/tool activity for spinner display."""

    def __init__(self) -> None:
        self._composing: bool = False
        self._buffer_length: int = 0
        self._tool_calls: dict[str, int] = {}
        self._sub_agent_tool_calls: dict[str, int] = {}
        self._sub_agent_tool_calls_by_id: dict[str, str] = {}

    def set_composing(self, composing: bool) -> None:
        self._composing = composing
        if not composing:
            self._buffer_length = 0

    def set_buffer_length(self, length: int) -> None:
        self._buffer_length = length

    def add_tool_call(self, tool_name: str) -> None:
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def add_sub_agent_tool_call(self, tool_call_id: str, tool_name: str) -> None:
        if tool_call_id in self._sub_agent_tool_calls_by_id:
            old_tool_name = self._sub_agent_tool_calls_by_id[tool_call_id]
            self._sub_agent_tool_calls[old_tool_name] = self._sub_agent_tool_calls.get(old_tool_name, 0) - 1
            if self._sub_agent_tool_calls[old_tool_name] <= 0:
                self._sub_agent_tool_calls.pop(old_tool_name, None)
        self._sub_agent_tool_calls_by_id[tool_call_id] = tool_name
        self._sub_agent_tool_calls[tool_name] = self._sub_agent_tool_calls.get(tool_name, 0) + 1

    def finish_sub_agent_tool_call(self, tool_call_id: str, tool_name: str | None = None) -> None:
        existing_tool_name = self._sub_agent_tool_calls_by_id.pop(tool_call_id, None)
        decremented_name = existing_tool_name or tool_name
        if decremented_name is None:
            return

        current = self._sub_agent_tool_calls.get(decremented_name, 0)
        if current <= 1:
            self._sub_agent_tool_calls.pop(decremented_name, None)
        else:
            self._sub_agent_tool_calls[decremented_name] = current - 1

    def clear_tool_calls(self) -> None:
        self._tool_calls = {}

    def clear_for_new_turn(self) -> None:
        self._composing = False
        self._buffer_length = 0
        self._tool_calls = {}

    def reset(self) -> None:
        self._composing = False
        self._buffer_length = 0
        self._tool_calls = {}
        self._sub_agent_tool_calls = {}
        self._sub_agent_tool_calls_by_id = {}

    def get_activity_text(self) -> Text | None:
        if self._tool_calls or self._sub_agent_tool_calls:
            activity_text = Text()

            def _append_counts(counts: dict[str, int]) -> None:
                first = True
                for name, count in counts.items():
                    if not first:
                        activity_text.append(", ")
                    activity_text.append(Text(name, style=ThemeKey.STATUS_TEXT_BOLD))
                    if count > 1:
                        activity_text.append(f" x {count}")
                    first = False

            if self._sub_agent_tool_calls:
                _append_counts(self._sub_agent_tool_calls)
                if self._tool_calls:
                    activity_text.append(", ")

            if self._tool_calls:
                _append_counts(self._tool_calls)

            return activity_text

        if self._composing:
            text = Text()
            text.append(STATUS_COMPOSING_TEXT, style=ThemeKey.STATUS_TEXT)
            if STATUS_SHOW_BUFFER_LENGTH and self._buffer_length > 0:
                text.append(f" ({self._buffer_length:,})", style=ThemeKey.STATUS_TEXT)
            return text

        return None


class SpinnerStatusState:
    """Multi-layer spinner status state management."""

    def __init__(self) -> None:
        self._todo_status: str | None = None
        self._reasoning_status: str | None = None
        self._toast_status: str | None = None
        self._activity = ActivityState()
        self._context_percent: float | None = None

    def reset(self) -> None:
        self._todo_status = None
        self._reasoning_status = None
        self._toast_status = None
        self._activity.reset()
        self._context_percent = None

    def set_toast_status(self, status: str | None) -> None:
        self._toast_status = status

    def set_todo_status(self, status: str | None) -> None:
        self._todo_status = status

    def set_reasoning_status(self, status: str | None) -> None:
        self._reasoning_status = status

    def clear_default_reasoning_status(self) -> None:
        """Clear reasoning status only if it's the default 'Reasoning ...' text."""
        if self._reasoning_status == STATUS_THINKING_TEXT:
            self._reasoning_status = None

    def set_composing(self, composing: bool) -> None:
        if composing:
            self._reasoning_status = None
        self._activity.set_composing(composing)

    def set_buffer_length(self, length: int) -> None:
        self._activity.set_buffer_length(length)

    def add_tool_call(self, tool_name: str) -> None:
        self._activity.add_tool_call(tool_name)

    def clear_tool_calls(self) -> None:
        self._activity.clear_tool_calls()

    def add_sub_agent_tool_call(self, tool_call_id: str, tool_name: str) -> None:
        self._activity.add_sub_agent_tool_call(tool_call_id, tool_name)

    def finish_sub_agent_tool_call(self, tool_call_id: str, tool_name: str | None = None) -> None:
        self._activity.finish_sub_agent_tool_call(tool_call_id, tool_name)

    def clear_for_new_turn(self) -> None:
        self._activity.clear_for_new_turn()

    def set_context_percent(self, percent: float) -> None:
        self._context_percent = percent

    def get_activity_text(self) -> Text | None:
        """Expose current activity for tests and UI composition."""
        return self._activity.get_activity_text()

    def get_status(self) -> Text:
        if self._toast_status:
            return Text(self._toast_status, style=ThemeKey.STATUS_TOAST)

        activity_text = self._activity.get_activity_text()
        todo_status = self._todo_status
        reasoning_status = self._reasoning_status

        if todo_status is not None:
            base_status = todo_status
            extra_reasoning = None if reasoning_status in (None, STATUS_THINKING_TEXT) else reasoning_status
        else:
            base_status = reasoning_status
            extra_reasoning = None

        if extra_reasoning is not None:
            if activity_text is None:
                activity_text = Text(extra_reasoning, style=ThemeKey.STATUS_TEXT_BOLD_ITALIC)
            else:
                prefixed = Text(extra_reasoning, style=ThemeKey.STATUS_TEXT_BOLD_ITALIC)
                prefixed.append(" , ")
                prefixed.append_text(activity_text)
                activity_text = prefixed

        if base_status:
            # Default "Thinking ..." uses normal style; custom headers use bold italic
            is_default_reasoning = base_status in {STATUS_THINKING_TEXT, STATUS_RUNNING_TEXT}
            status_style = ThemeKey.STATUS_TEXT if is_default_reasoning else ThemeKey.STATUS_TEXT_BOLD_ITALIC
            if activity_text:
                result = Text()
                result.append(base_status, style=status_style)
                result.append(" | ")
                result.append_text(activity_text)
            else:
                result = Text(base_status, style=status_style)
        elif activity_text:
            activity_text.append(" …")
            result = activity_text
        else:
            result = Text(STATUS_DEFAULT_TEXT, style=ThemeKey.STATUS_TEXT)

        return result

    def get_right_text(self) -> r_status.DynamicText | None:
        elapsed_text = r_status.current_elapsed_text()
        has_context = self._context_percent is not None
        if elapsed_text is None and not has_context:
            return None

        def _render() -> Text:
            parts: list[str] = []
            if self._context_percent is not None:
                parts.append(f"{self._context_percent:.1f}%")
            current_elapsed = r_status.current_elapsed_text()
            if current_elapsed is not None:
                if parts:
                    parts.append(" · ")
                parts.append(current_elapsed)
            return Text("".join(parts), style=ThemeKey.METADATA_DIM)

        return r_status.DynamicText(_render)


@dataclass
class _SessionState:
    session_id: str
    sub_agent_state: model.SubAgentState | None = None
    model_id: str | None = None
    assistant_stream_active: bool = False
    thinking_stream_active: bool = False
    assistant_char_count: int = 0
    thinking_tail: str = ""
    task_active: bool = False

    @property
    def is_sub_agent(self) -> bool:
        return self.sub_agent_state is not None

    @property
    def should_show_sub_agent_thinking_header(self) -> bool:
        return bool(self.sub_agent_state and self.sub_agent_state.sub_agent_type == tools.IMAGE_GEN)

    @property
    def should_extract_reasoning_header(self) -> bool:
        """Gemini and GPT-5 models use markdown bold headers in thinking."""
        return False  # Temporarily disabled for all models
        if self.model_id is None:
            return False
        model_lower = self.model_id.lower()
        return "gemini" in model_lower or "gpt-5" in model_lower

    def should_skip_tool_activity(self, tool_name: str) -> bool:
        """Check if tool activity should be skipped for non-streaming models."""
        if self.model_id is None:
            return False
        if tool_name not in FAST_TOOLS:
            return False
        model_lower = self.model_id.lower()
        return "gemini" in model_lower or "grok" in model_lower


class DisplayStateMachine:
    """Simplified, session-aware REPL UI state machine.

    This machine is deterministic because protocol events have explicit streaming
    boundaries (Start/Delta/End).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}
        self._primary_session_id: str | None = None
        self._spinner = SpinnerStatusState()

    def _session(self, session_id: str) -> _SessionState:
        existing = self._sessions.get(session_id)
        if existing is not None:
            return existing
        st = _SessionState(session_id=session_id)
        self._sessions[session_id] = st
        return st

    def _is_primary(self, session_id: str) -> bool:
        return self._primary_session_id == session_id

    def _set_primary_if_needed(self, session_id: str) -> None:
        if self._primary_session_id is None:
            self._primary_session_id = session_id

    def _spinner_update_commands(self) -> list[RenderCommand]:
        return [
            SpinnerUpdate(
                status_text=self._spinner.get_status(),
                right_text=self._spinner.get_right_text(),
            )
        ]

    def show_sigint_exit_toast(self) -> list[RenderCommand]:
        self._spinner.set_toast_status(SIGINT_DOUBLE_PRESS_EXIT_TEXT)
        return self._spinner_update_commands()

    def clear_sigint_exit_toast(self) -> list[RenderCommand]:
        self._spinner.set_toast_status(None)
        return self._spinner_update_commands()

    def begin_replay(self) -> list[RenderCommand]:
        self._spinner.reset()
        return [SpinnerStop(), PrintBlankLine()]

    def end_replay(self) -> list[RenderCommand]:
        return [SpinnerStop()]

    def transition_replay(self, event: events.Event) -> list[RenderCommand]:
        return self._transition(event, is_replay=True)

    def transition(self, event: events.Event) -> list[RenderCommand]:
        return self._transition(event, is_replay=False)

    def _transition(self, event: events.Event, *, is_replay: bool) -> list[RenderCommand]:
        session_id = getattr(event, "session_id", "__app__")
        s = self._session(session_id)
        cmds: list[RenderCommand] = []

        match event:
            case events.WelcomeEvent() as e:
                cmds.append(RenderWelcome(e))
                return cmds

            case events.UserMessageEvent() as e:
                if s.is_sub_agent:
                    return []
                cmds.append(RenderUserMessage(e))
                return cmds

            case events.BashCommandStartEvent() as e:
                if s.is_sub_agent:
                    return []
                if not is_replay:
                    self._spinner.set_reasoning_status(STATUS_RUNNING_TEXT)
                    cmds.append(TaskClockStart())
                    cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())

                cmds.append(RenderBashCommandStart(e))
                return cmds

            case events.BashCommandOutputDeltaEvent() as e:
                if s.is_sub_agent:
                    return []
                cmds.append(AppendBashCommandOutput(e))
                return cmds

            case events.BashCommandEndEvent() as e:
                if s.is_sub_agent:
                    return []
                cmds.append(RenderBashCommandEnd(e))

                if not is_replay:
                    self._spinner.set_reasoning_status(None)
                    cmds.append(TaskClockClear())
                    cmds.append(SpinnerStop())
                    cmds.extend(self._spinner_update_commands())

                return cmds

            case events.TaskStartEvent() as e:
                s.sub_agent_state = e.sub_agent_state
                s.model_id = e.model_id
                s.task_active = True
                if not s.is_sub_agent:
                    self._set_primary_if_needed(e.session_id)
                    if not is_replay:
                        cmds.append(TaskClockStart())

                if not is_replay:
                    cmds.append(SpinnerStart())
                cmds.append(RenderTaskStart(e))
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CompactionStartEvent():
                if not is_replay:
                    self._spinner.set_reasoning_status(STATUS_COMPACTING_TEXT)
                    if not s.task_active:
                        cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CompactionEndEvent() as e:
                if not is_replay:
                    self._spinner.set_reasoning_status(None)
                    if not s.task_active:
                        cmds.append(SpinnerStop())
                    cmds.extend(self._spinner_update_commands())
                if e.summary and not e.aborted:
                    kept_brief = tuple((item.item_type, item.count, item.preview) for item in e.kept_items_brief)
                    cmds.append(RenderCompactionSummary(summary=e.summary, kept_items_brief=kept_brief))
                return cmds

            case events.DeveloperMessageEvent() as e:
                cmds.append(RenderDeveloperMessage(e))
                return cmds

            case events.CommandOutputEvent() as e:
                cmds.append(RenderCommandOutput(e))
                return cmds

            case events.TurnStartEvent() as e:
                cmds.append(RenderTurnStart(e))
                if not is_replay:
                    self._spinner.clear_for_new_turn()
                    self._spinner.set_reasoning_status(None)
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.ThinkingStartEvent() as e:
                if s.is_sub_agent:
                    if not s.should_show_sub_agent_thinking_header:
                        return []
                    s.thinking_stream_active = True
                    cmds.append(StartThinkingStream(session_id=e.session_id))
                    return cmds
                if not self._is_primary(e.session_id):
                    return []
                s.thinking_stream_active = True
                s.thinking_tail = ""
                # Ensure the status reflects that reasoning has started even
                # before we receive any deltas (or a bold header).
                if not is_replay:
                    self._spinner.set_reasoning_status(STATUS_THINKING_TEXT)
                cmds.append(StartThinkingStream(session_id=e.session_id))
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.ThinkingDeltaEvent() as e:
                if s.is_sub_agent:
                    if not s.should_show_sub_agent_thinking_header:
                        return []
                    cmds.append(AppendThinking(session_id=e.session_id, content=e.content))
                    return cmds

                if not self._is_primary(e.session_id):
                    return []
                cmds.append(AppendThinking(session_id=e.session_id, content=e.content))

                # Update reasoning status for spinner (based on bounded tail).
                # Only extract headers for models that use markdown bold headers in thinking.
                if not is_replay and s.should_extract_reasoning_header:
                    s.thinking_tail = (s.thinking_tail + e.content)[-8192:]
                    header = extract_last_bold_header(normalize_thinking_content(s.thinking_tail))
                    if header:
                        self._spinner.set_reasoning_status(header)
                        cmds.extend(self._spinner_update_commands())

                return cmds

            case events.ThinkingEndEvent() as e:
                if s.is_sub_agent:
                    if not s.should_show_sub_agent_thinking_header:
                        return []
                    s.thinking_stream_active = False
                    cmds.append(EndThinkingStream(session_id=e.session_id))
                    return cmds
                if not self._is_primary(e.session_id):
                    return []
                s.thinking_stream_active = False
                if not is_replay:
                    self._spinner.clear_default_reasoning_status()
                cmds.append(EndThinkingStream(session_id=e.session_id))
                if not is_replay:
                    cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.AssistantTextStartEvent() as e:
                if s.is_sub_agent:
                    if not is_replay:
                        self._spinner.set_composing(True)
                        cmds.extend(self._spinner_update_commands())
                    return cmds
                if not self._is_primary(e.session_id):
                    return []

                s.assistant_stream_active = True
                s.assistant_char_count = 0
                if not is_replay:
                    self._spinner.set_composing(True)
                    self._spinner.clear_tool_calls()
                cmds.append(StartAssistantStream(session_id=e.session_id))
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.AssistantTextDeltaEvent() as e:
                if s.is_sub_agent:
                    return []
                if not self._is_primary(e.session_id):
                    return []

                s.assistant_char_count += len(e.content)
                if not is_replay:
                    self._spinner.set_buffer_length(s.assistant_char_count)
                cmds.append(AppendAssistant(session_id=e.session_id, content=e.content))
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.AssistantTextEndEvent() as e:
                if s.is_sub_agent:
                    if not is_replay:
                        self._spinner.set_composing(False)
                        cmds.extend(self._spinner_update_commands())
                    return cmds
                if not self._is_primary(e.session_id):
                    return []

                s.assistant_stream_active = False
                if not is_replay:
                    self._spinner.set_composing(False)
                cmds.append(EndAssistantStream(session_id=e.session_id))
                if not is_replay:
                    cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.AssistantImageDeltaEvent() as e:
                cmds.append(RenderAssistantImage(session_id=e.session_id, file_path=e.file_path))
                return cmds

            case events.ResponseCompleteEvent() as e:
                if s.is_sub_agent:
                    return []
                if not self._is_primary(e.session_id):
                    return []

                # Some providers/models may not emit fine-grained AssistantText* deltas.
                # In that case, ResponseCompleteEvent.content is the only assistant text we get.
                # Render it as a single assistant stream to avoid dropping the entire message.
                content = e.content
                if content.strip():
                    # If we saw no streamed assistant text for this response, render from the final snapshot.
                    if s.assistant_char_count == 0:
                        if not s.assistant_stream_active:
                            s.assistant_stream_active = True
                            cmds.append(StartAssistantStream(session_id=e.session_id))
                        cmds.append(AppendAssistant(session_id=e.session_id, content=content))
                        s.assistant_char_count += len(content)

                    # Ensure any active assistant stream is finalized.
                    if s.assistant_stream_active:
                        s.assistant_stream_active = False
                        cmds.append(EndAssistantStream(session_id=e.session_id))
                else:
                    # If there is an active stream but the final snapshot has no text,
                    # still finalize to flush any pending markdown rendering.
                    if s.assistant_stream_active:
                        s.assistant_stream_active = False
                        cmds.append(EndAssistantStream(session_id=e.session_id))

                if not is_replay:
                    self._spinner.set_composing(False)
                    cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.ToolCallStartEvent() as e:
                # Defensive: ensure any active main-session streams are finalized
                # before tools start producing output.
                if self._primary_session_id is not None:
                    primary = self._sessions.get(self._primary_session_id)
                    if primary is not None and primary.assistant_stream_active:
                        primary.assistant_stream_active = False
                        cmds.append(EndAssistantStream(session_id=primary.session_id))
                    if primary is not None and primary.thinking_stream_active:
                        primary.thinking_stream_active = False
                        cmds.append(EndThinkingStream(session_id=primary.session_id))

                if not is_replay:
                    self._spinner.set_composing(False)

                # Skip activity state for fast tools on non-streaming models (e.g., Gemini)
                # to avoid flash-and-disappear effect
                if not is_replay and not s.should_skip_tool_activity(e.tool_name):
                    tool_active_form = get_tool_active_form(e.tool_name)
                    if is_sub_agent_tool(e.tool_name):
                        self._spinner.add_sub_agent_tool_call(e.tool_call_id, tool_active_form)
                    else:
                        self._spinner.add_tool_call(tool_active_form)

                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.ToolCallEvent() as e:
                # Same defensive behavior for tool calls that arrive without a
                # preceding ToolCallStartEvent.
                if self._primary_session_id is not None:
                    primary = self._sessions.get(self._primary_session_id)
                    if primary is not None and primary.assistant_stream_active:
                        primary.assistant_stream_active = False
                        cmds.append(EndAssistantStream(session_id=primary.session_id))
                    if primary is not None and primary.thinking_stream_active:
                        primary.thinking_stream_active = False
                        cmds.append(EndThinkingStream(session_id=primary.session_id))

                if not is_replay and e.tool_name == tools.TASK and not s.should_skip_tool_activity(e.tool_name):
                    tool_active_form = get_task_active_form(e.arguments)
                    self._spinner.add_sub_agent_tool_call(e.tool_call_id, tool_active_form)
                    cmds.extend(self._spinner_update_commands())

                cmds.append(RenderToolCall(e))
                return cmds

            case events.ToolResultEvent() as e:
                if not is_replay and is_sub_agent_tool(e.tool_name):
                    self._spinner.finish_sub_agent_tool_call(e.tool_call_id)
                    cmds.extend(self._spinner_update_commands())

                if s.is_sub_agent and not e.is_error:
                    return cmds

                cmds.append(RenderToolResult(event=e, is_sub_agent_session=s.is_sub_agent))
                return cmds

            case events.TaskMetadataEvent() as e:
                cmds.append(EndThinkingStream(e.session_id))
                cmds.append(EndAssistantStream(e.session_id))
                cmds.append(RenderTaskMetadata(e))
                if is_replay:
                    cmds.append(PrintBlankLine())
                return cmds

            case events.TodoChangeEvent() as e:
                todo_text = _extract_active_form_text(e)
                if not is_replay:
                    self._spinner.set_todo_status(todo_text)
                    self._spinner.clear_for_new_turn()
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.UsageEvent() as e:
                # UsageEvent is not rendered, but it drives context % display.
                if s.is_sub_agent:
                    return []
                if not self._is_primary(e.session_id):
                    return []
                context_percent = e.usage.context_usage_percent
                if not is_replay and context_percent is not None:
                    self._spinner.set_context_percent(context_percent)
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.TurnEndEvent():
                return []

            case events.TaskFinishEvent() as e:
                s.task_active = False
                cmds.append(RenderTaskFinish(e))
                if not s.is_sub_agent and not is_replay:
                    cmds.append(TaskClockClear())
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                    cmds.append(EmitTmuxSignal())
                return cmds

            case events.InterruptEvent() as e:
                if not is_replay:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                s.task_active = False
                cmds.append(EndThinkingStream(session_id=e.session_id))
                cmds.append(EndAssistantStream(session_id=e.session_id))
                if not is_replay:
                    cmds.append(TaskClockClear())
                cmds.append(RenderInterrupt(session_id=e.session_id))
                return cmds

            case events.ErrorEvent() as e:
                if not is_replay:
                    cmds.append(EmitOsc94Error())
                cmds.append(RenderError(e))
                if not is_replay and not e.can_retry:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.EndEvent():
                if not is_replay:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                    cmds.append(TaskClockClear())
                return cmds

            case _:
                return []


def _extract_active_form_text(todo_event: events.TodoChangeEvent) -> str | None:
    status_text: str | None = None
    for todo in todo_event.todos:
        if todo.status == "in_progress" and todo.content:
            status_text = todo.content

    if status_text is None:
        return None

    normalized = status_text.replace("\n", " ").strip()
    return normalized if normalized else None
