from __future__ import annotations

from dataclasses import dataclass, field

from rich.cells import cell_len
from rich.text import Text

from klaude_code.const import (
    DEFAULT_MAX_TOKENS,
    SIGINT_DOUBLE_PRESS_EXIT_TEXT,
    STATUS_COMPACTING_TEXT,
    STATUS_COMPOSING_TEXT,
    STATUS_DEFAULT_TEXT,
    STATUS_RUNNING_TEXT,
    STATUS_SHOW_BUFFER_LENGTH,
    STATUS_THINKING_TEXT,
)
from klaude_code.protocol import events, model, tools
from klaude_code.protocol.model_id import is_gemini_model_any, is_grok_model
from klaude_code.protocol.sub_agent import get_sub_agent_profile
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
    RenderRewind,
    RenderTaskFinish,
    RenderTaskMetadata,
    RenderTaskStart,
    RenderToolCall,
    RenderToolResult,
    RenderTurnStart,
    RenderUserMessage,
    RenderWelcome,
    SpinnerStart,
    SpinnerStatusLine,
    SpinnerStop,
    SpinnerUpdate,
    StartAssistantStream,
    StartThinkingStream,
    TaskClockClear,
    TaskClockStart,
    UpdateTerminalTitlePrefix,
)
from klaude_code.tui.components.rich import status as r_status
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import get_task_active_form, get_tool_active_form, is_sub_agent_tool
from klaude_code.ui.common import format_number

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
        tools.REWIND,
    }
)

STATUS_LEFT_MIN_WIDTH_CELLS = 10
SUB_AGENT_STATUS_MAX_LINES = 5


def _normalize_status_text(text: str | None) -> str:
    if text is None:
        return ""
    return text.replace("\n", " ").strip()


def _empty_status_tool_counts() -> dict[str, int]:
    return {}


def _empty_status_tool_ids() -> dict[str, str]:
    return {}


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
                        activity_text.append(", ", style=ThemeKey.STATUS_TEXT)
                    activity_text.append(Text(name, style=ThemeKey.STATUS_TEXT))
                    if count > 1:
                        activity_text.append(f" x {count}", style=ThemeKey.STATUS_TEXT)
                    first = False

            if self._sub_agent_tool_calls:
                _append_counts(self._sub_agent_tool_calls)
                if self._tool_calls:
                    activity_text.append(", ", style=ThemeKey.STATUS_TEXT)

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
        self._token_input: int | None = None
        self._token_cached: int | None = None
        self._token_output: int | None = None
        self._token_thought: int | None = None
        self._token_image: int | None = None
        self._cache_hit_rate: float | None = None
        self._context_size: int | None = None
        self._context_effective_limit: int | None = None
        self._context_percent: float | None = None

    def reset(self) -> None:
        self._todo_status = None
        self._reasoning_status = None
        self._toast_status = None
        self._activity.reset()
        self._token_input = None
        self._token_cached = None
        self._token_output = None
        self._token_thought = None
        self._token_image = None
        self._cache_hit_rate = None
        self._context_size = None
        self._context_effective_limit = None
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

    def set_context_usage(self, usage: model.Usage) -> None:
        has_token_usage = any(
            (
                usage.input_tokens,
                usage.cached_tokens,
                usage.output_tokens,
                usage.reasoning_tokens,
                usage.image_tokens,
            )
        )
        if has_token_usage:
            self._token_input = (self._token_input or 0) + max(usage.input_tokens - usage.cached_tokens, 0)
            self._token_cached = (self._token_cached or 0) + usage.cached_tokens
            self._token_output = (self._token_output or 0) + max(usage.output_tokens - usage.reasoning_tokens, 0)
            self._token_thought = (self._token_thought or 0) + usage.reasoning_tokens
            self._token_image = (self._token_image or 0) + usage.image_tokens

        context_percent = usage.context_usage_percent
        if context_percent is not None:
            effective_limit = (usage.context_limit or 0) - (usage.max_tokens or DEFAULT_MAX_TOKENS)
            self._context_size = usage.context_size
            self._context_effective_limit = effective_limit if effective_limit > 0 else None
            self._context_percent = context_percent

    def set_cache_hit_rate(self, cache_hit_rate: float) -> None:
        self._cache_hit_rate = cache_hit_rate

    def get_activity_text(self) -> Text | None:
        """Expose current activity for tests and UI composition."""
        return self._activity.get_activity_text()

    def get_todo_status(self) -> Text:
        todo_status = self._todo_status
        if todo_status is None:
            return Text("")

        todo_status_cells = cell_len(todo_status)
        min_status_cells = STATUS_LEFT_MIN_WIDTH_CELLS
        if todo_status_cells < min_status_cells:
            todo_status = todo_status + " " * (min_status_cells - todo_status_cells)
        return Text(todo_status, style=ThemeKey.STATUS_TODO)

    def get_status(self) -> Text:
        if self._toast_status:
            return Text(self._toast_status, style=ThemeKey.STATUS_TOAST)

        reasoning_status = self._reasoning_status
        activity_text = self._activity.get_activity_text()

        if reasoning_status is not None:
            status_text = Text(reasoning_status, style=ThemeKey.STATUS_TEXT)
            if activity_text:
                status_text.append(" | ")
                status_text.append_text(activity_text)
        elif activity_text:
            status_text = activity_text
            if self._todo_status is None:
                activity_text.append(" …", style=ThemeKey.STATUS_TEXT)
        else:
            status_text = Text(STATUS_DEFAULT_TEXT, style=ThemeKey.STATUS_TEXT)

        status_cells = cell_len(status_text.plain)
        min_status_cells = STATUS_LEFT_MIN_WIDTH_CELLS
        if status_cells < min_status_cells:
            status_text.append(" " * (min_status_cells - status_cells), style=ThemeKey.STATUS_TEXT)
        return status_text

    def get_right_text(self) -> r_status.ResponsiveDynamicText | None:
        elapsed_text = r_status.current_elapsed_text()
        has_tokens = self._token_input is not None and self._token_output is not None
        has_context = (
            self._context_size is not None
            and self._context_effective_limit is not None
            and self._context_percent is not None
        )
        if elapsed_text is None and not has_tokens and not has_context:
            return None

        def _render(*, compact: bool) -> Text:
            parts: list[str] = []
            if self._token_input is not None and self._token_output is not None:
                if compact:
                    token_parts: list[str] = [f"↑{format_number(self._token_input)}"]
                else:
                    token_parts = [f"in {format_number(self._token_input)}"]
                if self._token_cached and self._token_cached > 0:
                    if compact:
                        cache_text = f"◎{format_number(self._token_cached)}"
                    else:
                        cache_text = f"cache {format_number(self._token_cached)}"
                    if not compact and self._cache_hit_rate is not None:
                        cache_text += f" ({self._cache_hit_rate:.0%})"
                    token_parts.append(cache_text)
                if compact:
                    token_parts.append(f"↓{format_number(self._token_output)}")
                else:
                    token_parts.append(f"out {format_number(self._token_output)}")
                if self._token_thought and self._token_thought > 0:
                    if compact:
                        token_parts.append(f"∿{format_number(self._token_thought)}")
                    else:
                        token_parts.append(f"thought {format_number(self._token_thought)}")
                if self._token_image and self._token_image > 0:
                    if compact:
                        token_parts.append(f"▣{format_number(self._token_image)}")
                    else:
                        token_parts.append(f"image {format_number(self._token_image)}")
                parts.append(" ".join(token_parts) if compact else " · ".join(token_parts))
            if (
                self._context_size is not None
                and self._context_effective_limit is not None
                and self._context_percent is not None
            ):
                if parts:
                    parts.append(" · ")
                parts.append(
                    f"{format_number(self._context_size)}/{format_number(self._context_effective_limit)} "
                    f"({self._context_percent:.1f}%)"
                )
            current_elapsed = r_status.current_elapsed_text()
            if current_elapsed is not None:
                if parts:
                    parts.append(" · ")
                parts.append(current_elapsed)
            return Text("".join(parts), style=ThemeKey.METADATA_DIM)

        return r_status.ResponsiveDynamicText(
            lambda: _render(compact=False),
            lambda: _render(compact=True),
        )


@dataclass
class _SessionState:
    session_id: str
    sub_agent_state: model.SubAgentState | None = None
    model_id: str | None = None
    assistant_stream_active: bool = False
    thinking_stream_active: bool = False
    assistant_char_count: int = 0
    task_active: bool = False
    status_composing: bool = False
    status_tool_calls: dict[str, int] = field(default_factory=_empty_status_tool_counts)
    status_tool_calls_by_id: dict[str, str] = field(default_factory=_empty_status_tool_ids)
    status_token_input: int | None = None
    status_token_cached: int | None = None
    status_token_output: int | None = None
    status_token_thought: int | None = None
    status_token_image: int | None = None
    status_context_size: int | None = None
    status_context_effective_limit: int | None = None
    status_context_percent: float | None = None

    @property
    def is_sub_agent(self) -> bool:
        return self.sub_agent_state is not None

    @property
    def should_show_sub_agent_thinking_header(self) -> bool:
        return bool(self.sub_agent_state and self.sub_agent_state.sub_agent_type == tools.IMAGE_GEN)

    def should_skip_tool_activity(self, tool_name: str) -> bool:
        """Check if tool activity should be skipped for non-streaming models."""
        if self.model_id is None:
            return False
        if tool_name not in FAST_TOOLS:
            return False
        return is_gemini_model_any(self.model_id) or is_grok_model(self.model_id)

    def clear_status_activity(self) -> None:
        self.status_composing = False
        self.status_tool_calls = {}
        self.status_tool_calls_by_id = {}

    def clear_status_metadata(self) -> None:
        self.status_token_input = None
        self.status_token_cached = None
        self.status_token_output = None
        self.status_token_thought = None
        self.status_token_image = None
        self.status_context_size = None
        self.status_context_effective_limit = None
        self.status_context_percent = None

    def set_status_usage(self, usage: model.Usage) -> None:
        has_token_usage = any(
            (
                usage.input_tokens,
                usage.cached_tokens,
                usage.output_tokens,
                usage.reasoning_tokens,
                usage.image_tokens,
            )
        )
        if has_token_usage:
            self.status_token_input = (self.status_token_input or 0) + max(usage.input_tokens - usage.cached_tokens, 0)
            self.status_token_cached = (self.status_token_cached or 0) + usage.cached_tokens
            self.status_token_output = (self.status_token_output or 0) + max(
                usage.output_tokens - usage.reasoning_tokens, 0
            )
            self.status_token_thought = (self.status_token_thought or 0) + usage.reasoning_tokens
            self.status_token_image = (self.status_token_image or 0) + usage.image_tokens

        context_percent = usage.context_usage_percent
        if context_percent is not None:
            effective_limit = (usage.context_limit or 0) - (usage.max_tokens or DEFAULT_MAX_TOKENS)
            self.status_context_size = usage.context_size
            self.status_context_effective_limit = effective_limit if effective_limit > 0 else None
            self.status_context_percent = context_percent

    def add_status_tool_call(self, tool_call_id: str, tool_name: str) -> None:
        if tool_call_id in self.status_tool_calls_by_id:
            old_tool_name = self.status_tool_calls_by_id[tool_call_id]
            old_count = self.status_tool_calls.get(old_tool_name, 0) - 1
            if old_count <= 0:
                self.status_tool_calls.pop(old_tool_name, None)
            else:
                self.status_tool_calls[old_tool_name] = old_count
        self.status_tool_calls_by_id[tool_call_id] = tool_name
        self.status_tool_calls[tool_name] = self.status_tool_calls.get(tool_name, 0) + 1

    def finish_status_tool_call(self, tool_call_id: str) -> None:
        tool_name = self.status_tool_calls_by_id.pop(tool_call_id, None)
        if tool_name is None:
            return
        current = self.status_tool_calls.get(tool_name, 0)
        if current <= 1:
            self.status_tool_calls.pop(tool_name, None)
        else:
            self.status_tool_calls[tool_name] = current - 1

    def status_title(self) -> str:
        if self.sub_agent_state is None:
            return "Tasking"
        try:
            profile = get_sub_agent_profile(self.sub_agent_state.sub_agent_type)
            active_form = profile.active_form.strip()
            if active_form:
                return active_form
        except KeyError:
            pass
        return self.sub_agent_state.sub_agent_type

    def status_description(self) -> str:
        if self.sub_agent_state is None:
            return ""
        return _normalize_status_text(self.sub_agent_state.sub_agent_desc)

    def status_activity_text(self) -> str | None:
        if self.status_tool_calls:
            return ", ".join(f"{name}×{count}" for name, count in self.status_tool_calls.items())
        if self.status_composing:
            return STATUS_COMPOSING_TEXT
        if self.thinking_stream_active:
            return STATUS_THINKING_TEXT
        return None

    def status_metadata_text(self) -> str | None:
        parts: list[str] = []
        if self.status_token_input is not None and self.status_token_output is not None:
            token_parts: list[str] = [f"↑{format_number(self.status_token_input)}"]
            if self.status_token_cached and self.status_token_cached > 0:
                token_parts.append(f"◎{format_number(self.status_token_cached)}")
            token_parts.append(f"↓{format_number(self.status_token_output)}")
            if self.status_token_thought and self.status_token_thought > 0:
                token_parts.append(f"∿{format_number(self.status_token_thought)}")
            if self.status_token_image and self.status_token_image > 0:
                token_parts.append(f"▣{format_number(self.status_token_image)}")
            parts.append(" ".join(token_parts))

        if (
            self.status_context_size is not None
            and self.status_context_effective_limit is not None
            and self.status_context_percent is not None
        ):
            if parts:
                parts.append(" · ")
            parts.append(
                f"{format_number(self.status_context_size)}/{format_number(self.status_context_effective_limit)} "
                f"({self.status_context_percent:.1f}%)"
            )

        if not parts:
            return None
        return "".join(parts)


class DisplayStateMachine:
    """Simplified, session-aware REPL UI state machine.

    This machine is deterministic because protocol events have explicit streaming
    boundaries (Start/Delta/End).
    """

    def __init__(self) -> None:
        self._sessions: dict[str, _SessionState] = {}
        self._primary_session_id: str | None = None
        self._spinner = SpinnerStatusState()
        self._model_name: str | None = None
        self._had_sub_agent_status_lines: bool = False

    def set_model_name(self, model_name: str | None) -> None:
        self._model_name = model_name

    def _reset_sessions(self) -> None:
        self._sessions = {}
        self._primary_session_id = None
        self._spinner.reset()
        self._had_sub_agent_status_lines = False

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

    def _sub_agent_status_lines(self) -> tuple[SpinnerStatusLine, ...]:
        lines: list[SpinnerStatusLine] = []
        for session in self._sessions.values():
            if not session.is_sub_agent or not session.task_active:
                continue
            title = session.status_title()
            description = session.status_description()
            if description:
                line = Text(f"{title}: {description}", style=ThemeKey.STATUS_TEXT)
            else:
                line = Text(title, style=ThemeKey.STATUS_TEXT)

            metadata = session.status_metadata_text()
            if metadata:
                line.append(" · ")
                line.append(metadata, style=ThemeKey.METADATA_DIM)

            activity = session.status_activity_text()
            if activity:
                line.append(" | ")
                line.append(activity, style=ThemeKey.STATUS_TEXT)
            lines.append(SpinnerStatusLine(text=line, session_id=session.session_id))

        if len(lines) <= SUB_AGENT_STATUS_MAX_LINES:
            return tuple(lines)

        hidden = len(lines) - SUB_AGENT_STATUS_MAX_LINES
        visible = lines[:SUB_AGENT_STATUS_MAX_LINES]
        visible.append(SpinnerStatusLine(text=Text(f"+{hidden} more...", style=ThemeKey.STATUS_HINT)))
        return tuple(visible)

    def _spinner_update_commands(self) -> list[RenderCommand]:
        sub_agent_lines = self._sub_agent_status_lines()
        status_lines = sub_agent_lines if sub_agent_lines else (SpinnerStatusLine(text=self._spinner.get_status()),)
        reset_bottom_height = self._had_sub_agent_status_lines and not sub_agent_lines
        self._had_sub_agent_status_lines = bool(sub_agent_lines)
        return [
            SpinnerUpdate(
                status_text=self._spinner.get_todo_status(),
                right_text=self._spinner.get_right_text(),
                status_lines=status_lines,
                reset_bottom_height=reset_bottom_height,
                leading_blank_line=bool(sub_agent_lines),
            )
        ]

    def show_sigint_exit_toast(self) -> list[RenderCommand]:
        self._spinner.set_toast_status(SIGINT_DOUBLE_PRESS_EXIT_TEXT)
        return self._spinner_update_commands()

    def clear_sigint_exit_toast(self) -> list[RenderCommand]:
        self._spinner.set_toast_status(None)
        return self._spinner_update_commands()

    def begin_replay(self) -> list[RenderCommand]:
        # Replay is a full rebuild of the terminal view; clear session state so primary-session
        # routing is recalculated from the replayed TaskStartEvent.
        self._reset_sessions()
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
                # WelcomeEvent marks (or reaffirms) the current interactive session.
                # If the session id changes (e.g., /clear creates a new session), clear
                # routing state so subsequent streamed events are not dropped.
                if self._primary_session_id is not None and self._primary_session_id != e.session_id:
                    self._reset_sessions()
                    s = self._session(e.session_id)
                self._primary_session_id = e.session_id
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
                s.clear_status_activity()
                s.clear_status_metadata()
                if not s.is_sub_agent:
                    # Keep primary session tracking in sync even if the session id changes
                    # during the process lifetime (e.g., /clear).
                    if is_replay:
                        self._set_primary_if_needed(e.session_id)
                    else:
                        self._primary_session_id = e.session_id
                    if not is_replay:
                        cmds.append(TaskClockStart())
                        cmds.append(UpdateTerminalTitlePrefix(prefix="\u26ac", model_name=self._model_name))

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

            case events.RewindEvent() as e:
                cmds.append(
                    RenderRewind(
                        checkpoint_id=e.checkpoint_id,
                        note=e.note,
                        rationale=e.rationale,
                        original_user_message=e.original_user_message,
                        messages_discarded=e.messages_discarded,
                    )
                )
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
                    if s.is_sub_agent:
                        s.clear_status_activity()
                    else:
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
                    if not is_replay:
                        cmds.extend(self._spinner_update_commands())
                    return cmds
                if not self._is_primary(e.session_id):
                    return []
                s.thinking_stream_active = True
                # Ensure the status reflects that reasoning has started even
                # before we receive any deltas.
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
                return cmds

            case events.ThinkingEndEvent() as e:
                if s.is_sub_agent:
                    if not s.should_show_sub_agent_thinking_header:
                        return []
                    s.thinking_stream_active = False
                    cmds.append(EndThinkingStream(session_id=e.session_id))
                    if not is_replay:
                        cmds.extend(self._spinner_update_commands())
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
                        s.status_composing = True
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
                        s.status_composing = False
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
                    if not is_replay:
                        s.status_composing = False
                        cmds.extend(self._spinner_update_commands())
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
                    if s.is_sub_agent:
                        s.status_composing = False
                    else:
                        self._spinner.set_composing(False)

                # Skip activity state for fast tools on non-streaming models (e.g., Gemini)
                # to avoid flash-and-disappear effect
                if not is_replay and not s.should_skip_tool_activity(e.tool_name):
                    tool_active_form = get_tool_active_form(e.tool_name)
                    if s.is_sub_agent:
                        s.add_status_tool_call(e.tool_call_id, tool_active_form)
                    else:
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

                if (
                    not is_replay
                    and s.is_sub_agent
                    and e.tool_name == tools.TASK
                    and not s.should_skip_tool_activity(e.tool_name)
                ):
                    tool_active_form = get_task_active_form(e.arguments)
                    s.add_status_tool_call(e.tool_call_id, tool_active_form)
                    cmds.extend(self._spinner_update_commands())
                elif (
                    not is_replay
                    and not s.is_sub_agent
                    and e.tool_name == tools.TASK
                    and not s.should_skip_tool_activity(e.tool_name)
                ):
                    tool_active_form = get_task_active_form(e.arguments)
                    self._spinner.add_sub_agent_tool_call(e.tool_call_id, tool_active_form)
                    cmds.extend(self._spinner_update_commands())

                cmds.append(RenderToolCall(e))
                return cmds

            case events.ToolResultEvent() as e:
                if not is_replay and s.is_sub_agent:
                    s.finish_status_tool_call(e.tool_call_id)
                    cmds.extend(self._spinner_update_commands())
                elif not is_replay and is_sub_agent_tool(e.tool_name):
                    self._spinner.finish_sub_agent_tool_call(e.tool_call_id)
                    cmds.extend(self._spinner_update_commands())

                if s.is_sub_agent and not e.is_error:
                    return cmds

                cmds.append(RenderToolResult(event=e, is_sub_agent_session=s.is_sub_agent))
                return cmds

            case events.TaskMetadataEvent() as e:
                cmds.append(EndThinkingStream(e.session_id))
                cmds.append(EndAssistantStream(e.session_id))
                if e.is_partial:
                    cmds.append(PrintBlankLine())
                cmds.append(RenderTaskMetadata(e))
                if is_replay or e.is_partial:
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
                    if not is_replay:
                        s.set_status_usage(e.usage)
                        cmds.extend(self._spinner_update_commands())
                    return cmds
                if not self._is_primary(e.session_id):
                    return []
                if not is_replay:
                    self._spinner.set_context_usage(e.usage)
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CacheHitRateEvent() as e:
                if s.is_sub_agent:
                    return []
                if not self._is_primary(e.session_id):
                    return []
                if not is_replay:
                    self._spinner.set_cache_hit_rate(e.cache_hit_rate)
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CacheHitWarnEvent():
                return []

            case events.TurnEndEvent():
                return []

            case events.TaskFinishEvent() as e:
                s.task_active = False
                s.clear_status_activity()
                s.clear_status_metadata()
                cmds.append(RenderTaskFinish(e))

                # Defensive: finalize any open streams so buffered markdown is flushed.
                if s.thinking_stream_active:
                    s.thinking_stream_active = False
                    cmds.append(EndThinkingStream(session_id=e.session_id))
                if s.assistant_stream_active:
                    s.assistant_stream_active = False
                    cmds.append(EndAssistantStream(session_id=e.session_id))

                # Rare providers / edge cases may complete a turn without emitting any
                # assistant deltas (or without the display consuming them). In that case,
                # fall back to rendering the final task result to avoid a "blank" turn.
                if (
                    not is_replay
                    and not s.is_sub_agent
                    and not e.has_structured_output
                    and s.assistant_char_count == 0
                    and e.task_result.strip()
                    and e.task_result.strip().lower() not in {"task cancelled", "task canceled"}
                ):
                    cmds.append(StartAssistantStream(session_id=e.session_id))
                    cmds.append(AppendAssistant(session_id=e.session_id, content=e.task_result))
                    cmds.append(EndAssistantStream(session_id=e.session_id))

                if not s.is_sub_agent and not is_replay:
                    cmds.append(TaskClockClear())
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                    cmds.append(EmitTmuxSignal())
                    cmds.append(UpdateTerminalTitlePrefix(prefix="\u2714", model_name=self._model_name))
                elif not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.InterruptEvent() as e:
                if not is_replay:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                s.task_active = False
                s.clear_status_activity()
                s.clear_status_metadata()
                cmds.append(EndThinkingStream(session_id=e.session_id))
                cmds.append(EndAssistantStream(session_id=e.session_id))
                if not is_replay:
                    cmds.append(TaskClockClear())
                else:
                    cmds.append(PrintBlankLine())
                cmds.append(RenderInterrupt(session_id=e.session_id))
                if is_replay:
                    cmds.append(PrintBlankLine())
                return cmds

            case events.ErrorEvent() as e:
                if not is_replay:
                    cmds.append(EmitOsc94Error())
                cmds.append(RenderError(e))
                if not is_replay and not e.can_retry:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                cmds.append(PrintBlankLine())
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
