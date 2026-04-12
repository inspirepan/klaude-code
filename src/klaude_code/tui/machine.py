from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto

from rich.cells import cell_len
from rich.text import Text

from klaude_code.config.formatters import format_number
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
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    RenderBashCommandEnd,
    RenderBashCommandStart,
    RenderCommand,
    RenderCompactionSummary,
    RenderDeveloperMessage,
    RenderError,
    RenderHandoff,
    RenderInterrupt,
    RenderNotice,
    RenderRewind,
    RenderSessionStats,
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
    StartTitleBlink,
    StopTitleBlink,
    TaskClockClear,
    TaskClockStart,
    UpdateTerminalTitlePrefix,
)
from klaude_code.tui.components.rich import status as r_status
from klaude_code.tui.components.rich.theme import ThemeKey
from klaude_code.tui.components.tools import get_agent_active_form, get_tool_active_form, is_sub_agent_tool
from klaude_code.tui.status_runtime import current_elapsed_text

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
        tools.APPLY_PATCH,
        tools.REWIND,
    }
)

STATUS_LEFT_MIN_WIDTH_CELLS = 10
SUB_AGENT_STATUS_MAX_LINES = 5
BASH_STREAM_DELAY_SEC = 3.0


def _empty_bash_chunks() -> list[str]:
    return []


@dataclass
class _PendingBashToolOutput:
    started_at: float
    chunks: list[str] = field(default_factory=_empty_bash_chunks)
    streaming_started: bool = False


def _normalize_status_text(text: str | None) -> str:
    if text is None:
        return ""
    return text.replace("\n", " ").strip()


def _empty_status_tool_counts() -> dict[str, int]:
    return {}


def _empty_status_tool_ids() -> dict[str, str]:
    return {}


class SpinnerPhase(Enum):
    WAITING = auto()
    THINKING = auto()
    COMPOSING = auto()
    COMPACTING = auto()
    RUNNING = auto()
    CUSTOM = auto()


class ActivityState:
    """Tracks tool activity for spinner display."""

    def __init__(self) -> None:
        self._tool_calls: dict[str, int] = {}
        self._sub_agent_tool_calls: dict[str, int] = {}
        self._sub_agent_tool_calls_by_id: dict[str, str] = {}

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
        self._tool_calls = {}

    def reset(self) -> None:
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
        return None


class SpinnerStatusState:
    """State machine for spinner status plus task/session metadata."""

    def __init__(self) -> None:
        self._todo_status: str | None = None
        self._phase = SpinnerPhase.WAITING
        self._custom_status: str | None = None
        self._toast_status: str | None = None
        self._composing_buffer_length: int = 0
        self._activity = ActivityState()
        self._token_input: int | None = None
        self._token_cached: int | None = None
        self._token_cache_write: int | None = None
        self._token_output: int | None = None
        self._token_thought: int | None = None
        self._cache_hit_rate: float | None = None
        self._context_size: int | None = None
        self._context_effective_limit: int | None = None
        self._context_percent: float | None = None
        self._cost_total: float | None = None
        self._cost_currency: str = "USD"

    def reset(self) -> None:
        self._todo_status = None
        self._enter_phase(SpinnerPhase.WAITING)
        self._toast_status = None
        self._activity.reset()
        self._token_input = None
        self._token_cached = None
        self._token_cache_write = None
        self._token_output = None
        self._token_thought = None
        self._cache_hit_rate = None
        self._context_size = None
        self._context_effective_limit = None
        self._context_percent = None
        self._cost_total = None
        self._cost_currency = "USD"

    def clear_task_state(self) -> None:
        """Clear task-scoped spinner state while keeping session metadata."""

        self._todo_status = None
        self._enter_phase(SpinnerPhase.WAITING)
        self._toast_status = None
        self._activity.reset()

    def _enter_phase(self, phase: SpinnerPhase, *, custom_status: str | None = None) -> None:
        self._phase = phase
        self._custom_status = custom_status if phase is SpinnerPhase.CUSTOM else None
        self._composing_buffer_length = 0

    def enter_waiting(self) -> None:
        self._enter_phase(SpinnerPhase.WAITING)

    def enter_thinking(self) -> None:
        self._enter_phase(SpinnerPhase.THINKING)

    def enter_compacting(self) -> None:
        self._enter_phase(SpinnerPhase.COMPACTING)

    def enter_running(self) -> None:
        self._enter_phase(SpinnerPhase.RUNNING)

    def set_toast_status(self, status: str | None) -> None:
        self._toast_status = status

    def set_todo_status(self, status: str | None) -> None:
        self._todo_status = status

    def set_reasoning_status(self, status: str | None) -> None:
        if status is None:
            self.enter_waiting()
            return
        if status == STATUS_THINKING_TEXT:
            self.enter_thinking()
            return
        if status == STATUS_COMPACTING_TEXT:
            self.enter_compacting()
            return
        if status == STATUS_RUNNING_TEXT:
            self.enter_running()
            return
        self._enter_phase(SpinnerPhase.CUSTOM, custom_status=status)

    def clear_default_reasoning_status(self) -> None:
        """Clear the phase only when the spinner is in the default thinking state."""
        if self._phase is SpinnerPhase.THINKING:
            self.enter_waiting()

    def set_composing(self, composing: bool) -> None:
        if composing:
            self._enter_phase(SpinnerPhase.COMPOSING)
            return
        if self._phase is SpinnerPhase.COMPOSING:
            self.enter_waiting()

    def set_buffer_length(self, length: int) -> None:
        if self._phase is SpinnerPhase.COMPOSING:
            self._composing_buffer_length = length

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
        if self._phase is SpinnerPhase.COMPOSING:
            self.enter_waiting()

    def set_context_usage(self, usage: model.Usage) -> None:
        has_token_usage = any(
            (
                usage.input_tokens,
                usage.cached_tokens,
                usage.cache_write_tokens,
                usage.output_tokens,
                usage.reasoning_tokens,
            )
        )
        if has_token_usage:
            self._token_input = (self._token_input or 0) + max(
                usage.input_tokens - usage.cached_tokens - usage.cache_write_tokens, 0
            )
            self._token_cached = (self._token_cached or 0) + usage.cached_tokens
            self._token_cache_write = (self._token_cache_write or 0) + usage.cache_write_tokens
            self._token_output = (self._token_output or 0) + max(usage.output_tokens - usage.reasoning_tokens, 0)
            self._token_thought = (self._token_thought or 0) + usage.reasoning_tokens

        context_percent = usage.context_usage_percent
        if context_percent is not None:
            effective_limit = (usage.context_limit or 0) - (usage.max_tokens or DEFAULT_MAX_TOKENS)
            self._context_size = usage.context_size
            self._context_effective_limit = effective_limit if effective_limit > 0 else None
            self._context_percent = context_percent

        total_cost = usage.total_cost
        if total_cost is not None:
            self._cost_total = (self._cost_total or 0.0) + total_cost
            self._cost_currency = usage.currency

    def set_cache_hit_rate(self, cache_hit_rate: float) -> None:
        self._cache_hit_rate = cache_hit_rate

    def get_activity_text(self) -> Text | None:
        """Expose current activity for tests and UI composition."""
        return self._activity.get_activity_text()

    def _base_status_text(self) -> Text | None:
        match self._phase:
            case SpinnerPhase.WAITING:
                return None
            case SpinnerPhase.THINKING:
                return Text(STATUS_THINKING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.COMPOSING:
                text = Text(STATUS_COMPOSING_TEXT, style=ThemeKey.STATUS_TEXT)
                if STATUS_SHOW_BUFFER_LENGTH and self._composing_buffer_length > 0:
                    text.append(f" ({self._composing_buffer_length:,})", style=ThemeKey.STATUS_TEXT)
                return text
            case SpinnerPhase.COMPACTING:
                return Text(STATUS_COMPACTING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.RUNNING:
                return Text(STATUS_RUNNING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.CUSTOM:
                return Text(self._custom_status or "", style=ThemeKey.STATUS_TEXT)
        return None

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

        base_status = self._base_status_text()
        activity_text = self._activity.get_activity_text()

        if self._phase is SpinnerPhase.COMPOSING and activity_text is not None:
            status_text = activity_text
            status_text.append("…", style=ThemeKey.STATUS_TEXT)
        elif base_status is not None:
            status_text = base_status
            if activity_text:
                status_text.append(" | ")
                status_text.append_text(activity_text)
        elif activity_text:
            status_text = activity_text
            status_text.append("…", style=ThemeKey.STATUS_TEXT)
        else:
            status_text = Text(STATUS_DEFAULT_TEXT, style=ThemeKey.STATUS_TEXT)

        status_cells = cell_len(status_text.plain)
        min_status_cells = STATUS_LEFT_MIN_WIDTH_CELLS
        if status_cells < min_status_cells:
            status_text.append(" " * (min_status_cells - status_cells), style=ThemeKey.STATUS_TEXT)
        return status_text

    def _build_metadata_text(self, *, compact: bool, include_elapsed: bool) -> Text | None:
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
            if self._token_cache_write and self._token_cache_write > 0:
                if compact:
                    token_parts.append(f"⊕{format_number(self._token_cache_write)}")
                else:
                    token_parts.append(f"cache+ {format_number(self._token_cache_write)}")
            if compact:
                token_parts.append(f"↓{format_number(self._token_output)}")
            else:
                token_parts.append(f"out {format_number(self._token_output)}")
            if self._token_thought and self._token_thought > 0:
                if compact:
                    token_parts.append(f"∿{format_number(self._token_thought)}")
                else:
                    token_parts.append(f"thought {format_number(self._token_thought)}")
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

        if self._cost_total is not None:
            if parts:
                parts.append(" · ")
            currency_symbol = "¥" if self._cost_currency == "CNY" else "$"
            if compact:
                parts.append(f"{currency_symbol}{self._cost_total:.4f}")
            else:
                parts.append(f"cost {currency_symbol}{self._cost_total:.4f}")

        if include_elapsed:
            current_elapsed = current_elapsed_text()
            if current_elapsed is not None:
                if parts:
                    parts.append(" · ")
                parts.append(current_elapsed)

        if not parts:
            return None
        return Text("".join(parts), style=ThemeKey.METADATA_DIM)

    def get_right_text(self) -> r_status.ResponsiveDynamicText | None:
        metadata_text = self._build_metadata_text(compact=False, include_elapsed=True)
        if metadata_text is None:
            return None

        def _render(*, compact: bool) -> Text:
            built = self._build_metadata_text(compact=compact, include_elapsed=True)
            return built if built is not None else Text("")

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

    @property
    def is_sub_agent(self) -> bool:
        return self.sub_agent_state is not None

    @property
    def should_show_sub_agent_thinking_header(self) -> bool:
        return False

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
            return ", ".join(f"{name} × {count}" for name, count in self.status_tool_calls.items())
        if self.status_composing:
            return STATUS_COMPOSING_TEXT
        if self.thinking_stream_active:
            return STATUS_THINKING_TEXT
        if self.task_active:
            return STATUS_RUNNING_TEXT
        return None


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
        self._session_title: str | None = None
        self._terminal_title_prefix: str | None = None
        self._had_sub_agent_status_lines: bool = False
        self._live_bash_tool_call_ids: set[str] = set()
        self._pending_bash_tool_outputs: dict[str, _PendingBashToolOutput] = {}
        self._bash_mode_output_chunks_by_session: dict[str, list[str]] = {}

    def set_model_name(self, model_name: str | None) -> None:
        self._model_name = model_name

    def set_session_title(self, title: str | None) -> None:
        self._session_title = title

    @property
    def terminal_title_prefix(self) -> str | None:
        return self._terminal_title_prefix

    @property
    def session_title(self) -> str | None:
        return self._session_title

    def _reset_sessions(self) -> None:
        self._sessions = {}
        self._primary_session_id = None
        self._spinner.reset()
        self._had_sub_agent_status_lines = False
        self._terminal_title_prefix = None
        self._live_bash_tool_call_ids = set()
        self._pending_bash_tool_outputs = {}
        self._bash_mode_output_chunks_by_session = {}

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

    def _clear_active_sub_agent_sessions(self) -> None:
        for session in self._sessions.values():
            if not session.is_sub_agent:
                continue
            session.task_active = False
            session.clear_status_activity()
            session.thinking_stream_active = False
            session.assistant_stream_active = False
            session.assistant_char_count = 0

    def _sub_agent_status_lines(self) -> tuple[SpinnerStatusLine, ...]:
        lines: list[SpinnerStatusLine] = []
        for session in self._sessions.values():
            if not session.is_sub_agent or not session.task_active:
                continue
            title = session.status_title()
            description = session.status_description()
            line = Text(title, style=ThemeKey.STATUS_TEXT)
            if description:
                line.append(": ", style=ThemeKey.STATUS_TEXT)
                description_start = len(line)
                line.append(description, style=ThemeKey.STATUS_TEXT)
                line.stylize("italic", description_start, len(line))

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

    @staticmethod
    def _notice_from_model_changed(event: events.ModelChangedEvent) -> events.NoticeEvent:
        default_note = " (saved as default)" if event.saved_as_default else ""
        return events.NoticeEvent(
            session_id=event.session_id,
            content=f"Switched to: {event.model_id}{default_note}",
        )

    @staticmethod
    def _notice_from_thinking_changed(event: events.ThinkingChangedEvent) -> events.NoticeEvent:
        return events.NoticeEvent(
            session_id=event.session_id,
            content=f"Thinking changed: {event.previous} -> {event.current}",
        )

    @staticmethod
    def _notice_from_sub_agent_model_changed(event: events.SubAgentModelChangedEvent) -> events.NoticeEvent:
        return events.NoticeEvent(
            session_id=event.session_id,
            content=f"{event.sub_agent_type} model: {event.model_display}",
        )

    @staticmethod
    def _notice_from_compact_model_changed(event: events.CompactModelChangedEvent) -> events.NoticeEvent:
        return events.NoticeEvent(
            session_id=event.session_id,
            content=f"Compact model: {event.model_display}",
        )

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
                # If the session id changes (e.g., /new creates a new session), clear
                # routing state so subsequent streamed events are not dropped.
                if self._primary_session_id is not None and self._primary_session_id != e.session_id:
                    self._reset_sessions()
                    s = self._session(e.session_id)
                self._primary_session_id = e.session_id
                self._session_title = e.title
                cmds.append(RenderWelcome(e))
                cmds.append(
                    UpdateTerminalTitlePrefix(
                        prefix=self._terminal_title_prefix,
                        model_name=self._model_name,
                        session_title=self._session_title,
                    )
                )
                return cmds

            case events.UserMessageEvent() as e:
                if s.is_sub_agent:
                    return []
                cmds.append(RenderUserMessage(e))
                return cmds

            case events.BashCommandStartEvent() as e:
                if s.is_sub_agent:
                    return []
                self._bash_mode_output_chunks_by_session[e.session_id] = []
                if not is_replay:
                    self._spinner.enter_running()
                    cmds.append(TaskClockStart())
                    cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())

                cmds.append(RenderBashCommandStart(e))
                return cmds

            case events.BashCommandOutputDeltaEvent() as e:
                if s.is_sub_agent:
                    return []
                chunks = self._bash_mode_output_chunks_by_session.get(e.session_id)
                if chunks is not None and e.content:
                    chunks.append(e.content)
                cmds.append(AppendBashCommandOutput(e))
                return cmds

            case events.BashCommandEndEvent() as e:
                if s.is_sub_agent:
                    return []
                cmds.append(RenderBashCommandEnd(e))

                buffered_chunks = self._bash_mode_output_chunks_by_session.pop(e.session_id, [])
                final_result = "".join(buffered_chunks).rstrip("\n")
                if e.cancelled:
                    final_result = f"{final_result}\nCommand cancelled" if final_result else "Command cancelled"
                elif e.exit_code not in (None, 0):
                    final_result = (
                        f"{final_result}\nCommand exited with code {e.exit_code}"
                        if final_result
                        else f"Command exited with code {e.exit_code}"
                    )

                cmds.append(
                    RenderToolResult(
                        event=events.ToolResultEvent(
                            session_id=e.session_id,
                            tool_call_id=f"bash-mode:{e.session_id}:{e.timestamp}",
                            tool_name=tools.BASH,
                            result=final_result,
                            status="aborted" if e.cancelled else "success",
                        ),
                        is_sub_agent_session=False,
                    )
                )

                if not is_replay:
                    self._spinner.enter_waiting()
                    cmds.append(TaskClockClear())
                    cmds.append(SpinnerStop())
                    cmds.extend(self._spinner_update_commands())

                return cmds

            case events.TaskStartEvent() as e:
                s.sub_agent_state = e.sub_agent_state
                s.model_id = e.model_id
                s.task_active = True
                s.clear_status_activity()
                if not s.is_sub_agent:
                    # Keep primary session tracking in sync even if the session id changes
                    # during the process lifetime (e.g., /new).
                    if is_replay:
                        self._set_primary_if_needed(e.session_id)
                    else:
                        self._primary_session_id = e.session_id
                    if not is_replay:
                        cmds.append(TaskClockStart())
                        self._terminal_title_prefix = "\u26ac"
                        cmds.append(
                            StartTitleBlink(
                                model_name=self._model_name,
                                session_title=self._session_title,
                            )
                        )

                if not is_replay:
                    cmds.append(SpinnerStart())
                cmds.append(RenderTaskStart(e))
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CompactionStartEvent():
                if not is_replay:
                    self._spinner.enter_compacting()
                    if not s.task_active:
                        cmds.append(SpinnerStart())
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CompactionEndEvent() as e:
                if not is_replay:
                    self._spinner.enter_waiting()
                    if not s.task_active:
                        cmds.append(SpinnerStop())
                    cmds.extend(self._spinner_update_commands())
                if e.summary and not e.aborted:
                    if e.reason == "handoff":
                        cmds.append(RenderHandoff(summary=e.summary))
                    else:
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

            case events.SessionTitleChangedEvent() as e:
                self._session_title = e.title
                cmds.append(
                    UpdateTerminalTitlePrefix(
                        prefix=self._terminal_title_prefix,
                        model_name=self._model_name,
                        session_title=self._session_title,
                    )
                )
                return cmds

            case events.NoticeEvent() as e:
                cmds.append(RenderNotice(e))
                return cmds

            case events.SessionStatsEvent() as e:
                cmds.append(RenderSessionStats(e))
                return cmds

            case events.ModelChangedEvent() as e:
                cmds.append(RenderNotice(self._notice_from_model_changed(e)))
                return cmds

            case events.ThinkingChangedEvent() as e:
                cmds.append(RenderNotice(self._notice_from_thinking_changed(e)))
                return cmds

            case events.SubAgentModelChangedEvent() as e:
                cmds.append(RenderNotice(self._notice_from_sub_agent_model_changed(e)))
                return cmds

            case events.CompactModelChangedEvent() as e:
                cmds.append(RenderNotice(self._notice_from_compact_model_changed(e)))
                return cmds

            case events.OperationRejectedEvent() as e:
                cmds.append(
                    RenderNotice(
                        events.NoticeEvent(
                            session_id=e.session_id,
                            content=(
                                "Operation rejected: session busy "
                                f"(operation={e.operation_type}, active_task_id={e.active_task_id or 'unknown'})"
                            ),
                            is_error=True,
                        ),
                    )
                )
                return cmds

            case events.TurnStartEvent() as e:
                cmds.append(RenderTurnStart(e))
                if not is_replay:
                    if s.is_sub_agent:
                        s.clear_status_activity()
                    else:
                        self._spinner.clear_for_new_turn()
                        self._spinner.enter_waiting()
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
                    self._spinner.enter_thinking()
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

            case events.ResponseCompleteEvent() as e:
                if s.is_sub_agent:
                    if not is_replay:
                        s.status_composing = False
                        cmds.extend(self._spinner_update_commands())
                    return []
                if not self._is_primary(e.session_id):
                    return []

                # Some providers/models may not emit fine-grained AssistantText* deltas.
                # Render from the final snapshot when no streamed text was received.
                content = e.content
                if content.strip() and s.assistant_char_count == 0:
                    if not s.assistant_stream_active:
                        s.assistant_stream_active = True
                        cmds.append(StartAssistantStream(session_id=e.session_id))
                    cmds.append(AppendAssistant(session_id=e.session_id, content=content))
                    s.assistant_char_count += len(content)

                # Finalize any active assistant stream to flush pending markdown.
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
                    elif is_sub_agent_tool(e.tool_name):
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

                if not is_replay and e.tool_name == tools.AGENT and not s.should_skip_tool_activity(e.tool_name):
                    tool_active_form = get_agent_active_form(e.arguments)
                    if s.is_sub_agent:
                        s.add_status_tool_call(e.tool_call_id, tool_active_form)
                    else:
                        self._spinner.add_sub_agent_tool_call(e.tool_call_id, tool_active_form)
                    cmds.extend(self._spinner_update_commands())

                if not s.is_sub_agent and e.tool_name == tools.BASH:
                    self._pending_bash_tool_outputs[e.tool_call_id] = _PendingBashToolOutput(started_at=e.timestamp)

                cmds.append(RenderToolCall(e))
                return cmds

            case events.ToolOutputDeltaEvent() as e:
                if s.is_sub_agent or e.tool_name != tools.BASH:
                    return []
                pending = self._pending_bash_tool_outputs.get(e.tool_call_id)
                if pending is None:
                    pending = _PendingBashToolOutput(started_at=e.timestamp)
                    self._pending_bash_tool_outputs[e.tool_call_id] = pending

                if not pending.streaming_started and e.timestamp - pending.started_at < BASH_STREAM_DELAY_SEC:
                    pending.chunks.append(e.content)
                    return []

                if not pending.streaming_started:
                    pending.streaming_started = True
                    self._live_bash_tool_call_ids.add(e.tool_call_id)
                    for chunk in pending.chunks:
                        cmds.append(
                            AppendBashCommandOutput(
                                events.BashCommandOutputDeltaEvent(session_id=e.session_id, content=chunk)
                            )
                        )
                    pending.chunks = []

                cmds.append(
                    AppendBashCommandOutput(
                        events.BashCommandOutputDeltaEvent(session_id=e.session_id, content=e.content)
                    )
                )
                return cmds

            case events.ToolResultEvent() as e:
                pending = self._pending_bash_tool_outputs.pop(e.tool_call_id, None)
                if not is_replay and s.is_sub_agent:
                    s.finish_status_tool_call(e.tool_call_id)
                    cmds.extend(self._spinner_update_commands())
                elif not is_replay and is_sub_agent_tool(e.tool_name):
                    self._spinner.finish_sub_agent_tool_call(e.tool_call_id)
                    if e.is_error and isinstance(e.ui_extra, model.SessionIdUIExtra):
                        failed_sub_session = self._sessions.get(e.ui_extra.session_id)
                        if failed_sub_session is not None and failed_sub_session.is_sub_agent:
                            failed_sub_session.task_active = False
                            failed_sub_session.clear_status_activity()
                    cmds.extend(self._spinner_update_commands())

                if e.tool_name == tools.BASH and e.tool_call_id in self._live_bash_tool_call_ids:
                    self._live_bash_tool_call_ids.discard(e.tool_call_id)
                    cmds.append(
                        RenderBashCommandEnd(
                            events.BashCommandEndEvent(
                                session_id=e.session_id,
                                cancelled=e.status == "aborted",
                            )
                        )
                    )
                elif pending is not None:
                    self._live_bash_tool_call_ids.discard(e.tool_call_id)

                if (
                    s.is_sub_agent
                    and not e.is_error
                    and e.tool_name
                    not in (tools.EDIT, tools.WRITE, tools.APPLY_PATCH, tools.TODO_WRITE, tools.ASK_USER_QUESTION)
                ):
                    return cmds

                cmds.append(RenderToolResult(event=e, is_sub_agent_session=s.is_sub_agent))
                return cmds

            case events.TaskMetadataEvent() as e:
                cmds.append(EndThinkingStream(e.session_id))
                cmds.append(EndAssistantStream(e.session_id))
                cmds.append(RenderTaskMetadata(e))
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
                self._spinner.set_context_usage(e.usage)
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.CacheHitRateEvent() as e:
                if s.is_sub_agent:
                    return []
                if not self._is_primary(e.session_id):
                    return []
                self._spinner.set_cache_hit_rate(e.cache_hit_rate)
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.TurnEndEvent():
                return []

            case events.TaskFinishEvent() as e:
                s.task_active = False
                s.clear_status_activity()
                cmds.append(RenderTaskFinish(e))
                if s.is_sub_agent:
                    cmds.append(PrintBlankLine())

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
                    and s.assistant_char_count == 0
                    and e.task_result.strip()
                    and e.task_result.strip().lower() not in {"task cancelled", "task canceled"}
                ):
                    cmds.append(StartAssistantStream(session_id=e.session_id))
                    cmds.append(AppendAssistant(session_id=e.session_id, content=e.task_result))
                    cmds.append(EndAssistantStream(session_id=e.session_id))

                if not s.is_sub_agent and not is_replay:
                    cmds.append(TaskClockClear())
                    self._spinner.clear_task_state()
                    cmds.append(SpinnerStop())
                    cmds.append(StopTitleBlink())
                    self._terminal_title_prefix = "\u2714"
                    cmds.append(
                        UpdateTerminalTitlePrefix(
                            prefix=self._terminal_title_prefix,
                            model_name=self._model_name,
                            session_title=self._session_title,
                        )
                    )
                elif not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.InterruptEvent() as e:
                if not is_replay:
                    self._spinner.clear_task_state()
                    cmds.append(SpinnerStop())
                s.task_active = False
                s.clear_status_activity()
                if not s.is_sub_agent:
                    self._terminal_title_prefix = None
                    self._clear_active_sub_agent_sessions()
                cmds.append(EndThinkingStream(session_id=e.session_id))
                cmds.append(EndAssistantStream(session_id=e.session_id))
                if not is_replay:
                    cmds.append(TaskClockClear())
                    if not s.is_sub_agent:
                        cmds.append(StopTitleBlink())
                        cmds.append(
                            UpdateTerminalTitlePrefix(
                                prefix=self._terminal_title_prefix,
                                model_name=self._model_name,
                                session_title=self._session_title,
                            )
                        )
                if e.show_notice:
                    cmds.append(RenderInterrupt(session_id=e.session_id))
                return cmds

            case events.ErrorEvent() as e:
                if not e.can_retry:
                    s.task_active = False
                    s.clear_status_activity()
                cmds.append(RenderError(e))
                if not is_replay and not e.can_retry:
                    self._spinner.clear_task_state()
                    cmds.append(SpinnerStop())
                if not is_replay:
                    cmds.extend(self._spinner_update_commands())
                return cmds

            case events.EndEvent():
                if not is_replay:
                    self._spinner.reset()
                    cmds.append(SpinnerStop())
                    cmds.append(TaskClockClear())
                    cmds.append(StopTitleBlink())
                    self._terminal_title_prefix = None
                    cmds.append(
                        UpdateTerminalTitlePrefix(
                            prefix=self._terminal_title_prefix,
                            model_name=self._model_name,
                            session_title=self._session_title,
                        )
                    )
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
