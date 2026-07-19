from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import ClassVar

from rich.cells import cell_len
from rich.text import Text

from klaude_code.config.formatters import format_number
from klaude_code.const import (
    DEFAULT_MAX_TOKENS,
    SIGINT_DOUBLE_PRESS_EXIT_TEXT,
    STATUS_COMPACTING_TEXT,
    STATUS_COMPOSING_TEXT,
    STATUS_DEFAULT_TEXT,
    STATUS_HANDOFF_TEXT,
    STATUS_HINT_TEXT,
    STATUS_RECAPPING_TEXT,
    STATUS_RUNNING_TEXT,
    STATUS_SHOW_BUFFER_LENGTH,
    STATUS_THINKING_TEXT,
)
from klaude_code.protocol import events, tools
from klaude_code.protocol.model_id import is_gemini_model_any, is_grok_model
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState, Usage
from klaude_code.tui.commands import (
    AppendAssistant,
    AppendBashCommandOutput,
    AppendThinking,
    DynamicSeparatorText,
    EndAssistantStream,
    EndThinkingStream,
    FlushOpenBlocks,
    PrintBlankLine,
    PrintRuleLine,
    RenderAwaySummary,
    RenderBashCommandEnd,
    RenderBashCommandStart,
    RenderCommand,
    RenderCompactionSummary,
    RenderDeveloperMessage,
    RenderError,
    RenderForkCacheHitRate,
    RenderHandoff,
    RenderInterrupt,
    RenderNotice,
    RenderRewind,
    RenderSessionStats,
    RenderTaskFileChangeSummary,
    RenderTaskFinish,
    RenderTaskMetadata,
    RenderTaskStart,
    RenderToolCall,
    RenderToolResult,
    RenderUserMessage,
    RenderWelcome,
    RenderWelcomeContext,
    SeparatorText,
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
from klaude_code.tui.components.common import format_elapsed_compact, format_more_lines_indicator, format_pascal_case
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


def is_cancelled_task_result(task_result: str) -> bool:
    return task_result.strip().lower() in {"task cancelled", "task canceled"}


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
    RECAPPING = auto()
    RUNNING = auto()
    CUSTOM = auto()


class ActivityState:
    """Tracks tool activity for spinner display."""

    def __init__(self) -> None:
        self._tool_calls: dict[str, int] = {}
        self._tool_calls_by_id: dict[str, str] = {}
        self._sub_agent_tool_calls: dict[str, int] = {}
        self._sub_agent_tool_calls_by_id: dict[str, str] = {}

    def add_tool_call(self, tool_name: str, tool_call_id: str | None = None) -> None:
        if tool_call_id is not None:
            self._set_tool_call_label(tool_call_id, tool_name)
            return
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def _set_tool_call_label(self, tool_call_id: str, tool_name: str) -> None:
        existing_tool_name = self._tool_calls_by_id.get(tool_call_id)
        if existing_tool_name is not None:
            self._decrement_tool_call(existing_tool_name)
        self._tool_calls_by_id[tool_call_id] = tool_name
        self._tool_calls[tool_name] = self._tool_calls.get(tool_name, 0) + 1

    def finish_tool_call(self, tool_call_id: str) -> None:
        tool_name = self._tool_calls_by_id.pop(tool_call_id, None)
        if tool_name is not None:
            self._decrement_tool_call(tool_name)

    def _decrement_tool_call(self, tool_name: str) -> None:
        current = self._tool_calls.get(tool_name, 0)
        if current <= 1:
            self._tool_calls.pop(tool_name, None)
        else:
            self._tool_calls[tool_name] = current - 1

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
        self._tool_calls_by_id = {}

    def clear_for_new_step(self) -> None:
        self._tool_calls = {}
        self._tool_calls_by_id = {}

    def reset(self) -> None:
        self._tool_calls = {}
        self._tool_calls_by_id = {}
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

    def has_activity_label(self, label: str) -> bool:
        return label in self._tool_calls or any(name.startswith(f"{label} ") for name in self._tool_calls)


class SpinnerStatusState:
    """State machine for spinner status plus task/session metadata."""

    def __init__(self) -> None:
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
        self._compaction_count: int = 0
        self._cost_total: float | None = None
        self._cost_currency: str = "USD"

    def reset(self) -> None:
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
        self._compaction_count = 0
        self._cost_total = None
        self._cost_currency = "USD"

    def clear_task_state(self) -> None:
        """Clear task-scoped spinner state while keeping session metadata."""

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

    def enter_recapping(self) -> None:
        self._enter_phase(SpinnerPhase.RECAPPING)

    def enter_running(self) -> None:
        self._enter_phase(SpinnerPhase.RUNNING)

    def set_toast_status(self, status: str | None) -> None:
        self._toast_status = status

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

    def add_tool_call(self, tool_name: str, tool_call_id: str | None = None) -> None:
        self._activity.add_tool_call(tool_name, tool_call_id)

    def finish_tool_call(self, tool_call_id: str) -> None:
        self._activity.finish_tool_call(tool_call_id)

    def clear_tool_calls(self) -> None:
        self._activity.clear_tool_calls()

    def add_sub_agent_tool_call(self, tool_call_id: str, tool_name: str) -> None:
        self._activity.add_sub_agent_tool_call(tool_call_id, tool_name)

    def finish_sub_agent_tool_call(self, tool_call_id: str, tool_name: str | None = None) -> None:
        self._activity.finish_sub_agent_tool_call(tool_call_id, tool_name)

    def clear_for_new_step(self) -> None:
        self._activity.clear_for_new_step()
        if self._phase is SpinnerPhase.COMPOSING:
            self.enter_waiting()

    def set_context_usage(self, usage: Usage) -> None:
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

    def notify_compaction(self) -> None:
        self._compaction_count += 1

    def set_cache_hit_rate(self, cache_hit_rate: float) -> None:
        self._cache_hit_rate = cache_hit_rate

    def get_activity_text(self) -> Text | None:
        """Expose current activity for tests and UI composition."""
        return self._activity.get_activity_text()

    def has_activity_label(self, label: str) -> bool:
        return self._activity.has_activity_label(label)

    def _base_status_text(self) -> Text | None:
        match self._phase:
            case SpinnerPhase.WAITING:
                return None
            case SpinnerPhase.THINKING:
                return Text(STATUS_THINKING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.COMPOSING:
                text = Text(STATUS_COMPOSING_TEXT, style=ThemeKey.STATUS_TEXT)
                if STATUS_SHOW_BUFFER_LENGTH and self._composing_buffer_length > 0:
                    text.append(f" ({self._composing_buffer_length:,} chars)", style=ThemeKey.STATUS_TEXT)
                return text
            case SpinnerPhase.COMPACTING:
                return Text(STATUS_COMPACTING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.RECAPPING:
                return Text(STATUS_RECAPPING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.RUNNING:
                return Text(STATUS_RUNNING_TEXT, style=ThemeKey.STATUS_TEXT)
            case SpinnerPhase.CUSTOM:
                return Text(self._custom_status or "", style=ThemeKey.STATUS_TEXT)

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
                    token_parts.append(f"∵{format_number(self._token_thought)}")
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
            if self._compaction_count > 0:
                parts.append(f" · compact {self._compaction_count}")

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
        metadata_text = self._build_metadata_text(compact=False, include_elapsed=False)
        if metadata_text is None:
            return None

        def _render(*, compact: bool) -> Text:
            built = self._build_metadata_text(compact=compact, include_elapsed=False)
            return built if built is not None else Text("")

        return r_status.ResponsiveDynamicText(
            lambda: _render(compact=False),
            lambda: _render(compact=True),
        )

    def get_separator_text(self) -> SeparatorText:
        return DynamicSeparatorText(self._build_separator_text)

    def _build_separator_text(self) -> str:
        elapsed = current_elapsed_text()
        if elapsed is None:
            return STATUS_HINT_TEXT
        return f"{elapsed} · {STATUS_HINT_TEXT}"


@dataclass
class _SessionState:
    session_id: str
    sub_agent_state: SubAgentState | None = None
    parent_session_id: str | None = None
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
        return format_pascal_case(self.sub_agent_state.sub_agent_type)

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

    # Event-type -> handler dispatch table, populated after the class body
    # (see module-level assignment) so entries can reference the methods.
    _EVENT_HANDLERS: ClassVar[dict[type[events.Event], Callable[..., list[RenderCommand]]]] = {}

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
        self._has_rendered_user_message = False
        self._skip_next_user_message_rule = False

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
        self._has_rendered_user_message = False
        self._skip_next_user_message_rule = False

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
        visible.append(SpinnerStatusLine(text=Text(format_more_lines_indicator(hidden), style=ThemeKey.STATUS_HINT)))
        return tuple(visible)

    def _spinner_update_commands(self) -> list[RenderCommand]:
        sub_agent_lines = self._sub_agent_status_lines()
        status_lines = sub_agent_lines if sub_agent_lines else (SpinnerStatusLine(text=self._spinner.get_status()),)
        reset_bottom_height = self._had_sub_agent_status_lines and not sub_agent_lines
        self._had_sub_agent_status_lines = bool(sub_agent_lines)
        top_blank_line = (
            self._spinner.has_activity_label(get_tool_active_form(tools.BASH)) and not self._live_bash_tool_call_ids
        )
        return [
            SpinnerUpdate(
                right_text=self._spinner.get_right_text(),
                status_lines=status_lines,
                separator_text=self._spinner.get_separator_text(),
                reset_bottom_height=reset_bottom_height,
                leading_blank_line=bool(sub_agent_lines),
                top_blank_line=top_blank_line,
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

    @staticmethod
    def _notice_from_fallback_model_config_warn(event: events.FallbackModelConfigWarnEvent) -> events.NoticeEvent:
        def _display(model: str, provider: str | None) -> str:
            return f"{model}@{provider}" if provider else model

        label = f"{event.sub_agent_type} model" if event.sub_agent_type else "Model"
        return events.NoticeEvent(
            session_id=event.session_id,
            content=(
                f"{label} fallback: {_display(event.from_model, event.from_provider)} -> "
                f"{_display(event.to_model, event.to_provider)} ({event.reason})"
            ),
            style="warn",
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
        handler = self._EVENT_HANDLERS.get(type(event))
        if handler is None:
            return []
        return handler(self, event, is_replay=is_replay, s=s)

    def _handle_WelcomeEvent(self, e: events.WelcomeEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        # WelcomeEvent marks (or reaffirms) the current interactive session.
        # If the session id changes (e.g., /new creates a new session), clear
        # routing state so subsequent streamed events are not dropped.
        if self._primary_session_id is not None and self._primary_session_id != e.session_id:
            self._reset_sessions()
            self._session(e.session_id)
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

    def _handle_WelcomeContextEvent(
        self, e: events.WelcomeContextEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        del is_replay, s
        return [RenderWelcomeContext(e)]

    def _handle_UserMessageEvent(
        self, e: events.UserMessageEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
        if self._has_rendered_user_message and not self._skip_next_user_message_rule:
            cmds.append(PrintRuleLine())
            cmds.append(PrintBlankLine())
        cmds.append(RenderUserMessage(e))
        self._has_rendered_user_message = True
        self._skip_next_user_message_rule = False
        return cmds

    def _handle_BashCommandStartEvent(
        self, e: events.BashCommandStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_BashCommandOutputDeltaEvent(
        self, e: events.BashCommandOutputDeltaEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
        chunks = self._bash_mode_output_chunks_by_session.get(e.session_id)
        if chunks is not None and e.content:
            chunks.append(e.content)
        cmds.append(AppendBashCommandOutput(e))
        return cmds

    def _handle_BashCommandEndEvent(
        self, e: events.BashCommandEndEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_TaskStartEvent(
        self, e: events.TaskStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        s.sub_agent_state = e.sub_agent_state
        s.parent_session_id = e.parent_session_id
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
                self._terminal_title_prefix = "⠋"
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

    def _handle_CompactionStartEvent(
        self, e: events.CompactionStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if not is_replay:
            if e.reason == "handoff":
                self._spinner.clear_tool_calls()
                self._spinner.set_reasoning_status(STATUS_HANDOFF_TEXT)
            else:
                self._spinner.enter_compacting()
            if not s.task_active:
                cmds.append(SpinnerStart())
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_CompactionEndEvent(
        self, e: events.CompactionEndEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if e.reason != "handoff" and not e.aborted and not s.is_sub_agent and self._is_primary(e.session_id):
            self._spinner.notify_compaction()
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

    def _handle_ForkCacheHitRateEvent(
        self, e: events.ForkCacheHitRateEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
        if not self._is_primary(e.session_id):
            return []
        cmds.append(
            RenderForkCacheHitRate(
                fork_label=e.fork_label,
                cache_read_tokens=e.cache_read_tokens,
                cache_creation_tokens=e.cache_creation_tokens,
                input_tokens=e.input_tokens,
                cache_hit_rate=e.cache_hit_rate,
                fallback_used=e.fallback_used,
            )
        )
        return cmds

    def _handle_RewindEvent(self, e: events.RewindEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_DeveloperMessageEvent(
        self, e: events.DeveloperMessageEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderDeveloperMessage(e))
        return cmds

    def _handle_SessionTitleChangedEvent(
        self, e: events.SessionTitleChangedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        self._session_title = e.title
        cmds.append(
            UpdateTerminalTitlePrefix(
                prefix=self._terminal_title_prefix,
                model_name=self._model_name,
                session_title=self._session_title,
            )
        )
        return cmds

    def _handle_NoticeEvent(self, e: events.NoticeEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(e))
        return cmds

    def _handle_AwaySummaryEvent(
        self, e: events.AwaySummaryEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderAwaySummary(e))
        return cmds

    def _handle_AwaySummaryStartEvent(
        self, e: events.AwaySummaryStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if not is_replay:
            self._spinner.enter_recapping()
            if not s.task_active:
                cmds.append(SpinnerStart())
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_AwaySummaryEndEvent(
        self, e: events.AwaySummaryEndEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if not is_replay:
            self._spinner.enter_waiting()
            if not s.task_active:
                cmds.append(SpinnerStop())
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_SessionStatsEvent(
        self, e: events.SessionStatsEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderSessionStats(e))
        return cmds

    def _handle_ModelChangedEvent(
        self, e: events.ModelChangedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(self._notice_from_model_changed(e)))
        return cmds

    def _handle_ThinkingChangedEvent(
        self, e: events.ThinkingChangedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(self._notice_from_thinking_changed(e)))
        return cmds

    def _handle_SubAgentModelChangedEvent(
        self, e: events.SubAgentModelChangedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(self._notice_from_sub_agent_model_changed(e)))
        return cmds

    def _handle_CompactModelChangedEvent(
        self, e: events.CompactModelChangedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(self._notice_from_compact_model_changed(e)))
        return cmds

    def _handle_FallbackModelConfigWarnEvent(
        self, e: events.FallbackModelConfigWarnEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(RenderNotice(self._notice_from_fallback_model_config_warn(e)))
        return cmds

    def _handle_OperationRejectedEvent(
        self, e: events.OperationRejectedEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_StepStartEvent(
        self, e: events.StepStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(FlushOpenBlocks())
        if not is_replay:
            if s.is_sub_agent:
                s.clear_status_activity()
            else:
                self._spinner.clear_for_new_step()
                self._spinner.enter_waiting()
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_ThinkingStartEvent(
        self, e: events.ThinkingStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
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

    def _handle_ThinkingDeltaEvent(
        self, e: events.ThinkingDeltaEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return cmds

        if not self._is_primary(e.session_id):
            return []
        cmds.append(AppendThinking(session_id=e.session_id, content=e.content))
        return cmds

    def _handle_ThinkingEndEvent(
        self, e: events.ThinkingEndEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
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

    def _handle_AssistantTextStartEvent(
        self, e: events.AssistantTextStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_AssistantTextDeltaEvent(
        self, e: events.AssistantTextDeltaEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_AssistantTextEndEvent(
        self, e: events.AssistantTextEndEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_ResponseCompleteEvent(
        self, e: events.ResponseCompleteEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_ToolCallStartEvent(
        self, e: events.ToolCallStartEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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
                self._spinner.add_tool_call(tool_active_form, e.tool_call_id)

        if not is_replay:
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_ToolCallEvent(
        self, e: events.ToolCallEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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

    def _handle_ToolLongRunningEvent(
        self, e: events.ToolLongRunningEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        if is_replay or e.tool_name == tools.AGENT:
            return []
        return [
            RenderNotice(
                events.NoticeEvent(
                    session_id=e.session_id,
                    content=f"Warning: {e.tool_name} has been running for {format_elapsed_compact(e.elapsed_seconds)}",
                    style="warn",
                )
            )
        ]

    def _handle_ToolOutputDeltaEvent(
        self, e: events.ToolOutputDeltaEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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
                    AppendBashCommandOutput(events.BashCommandOutputDeltaEvent(session_id=e.session_id, content=chunk))
                )
            pending.chunks = []

        cmds.append(
            AppendBashCommandOutput(events.BashCommandOutputDeltaEvent(session_id=e.session_id, content=e.content))
        )
        return cmds

    def _handle_ToolResultEvent(
        self, e: events.ToolResultEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if isinstance(e.ui_extra, SessionIdUIExtra):
            self._session(e.ui_extra.session_id).parent_session_id = e.session_id
        pending = self._pending_bash_tool_outputs.pop(e.tool_call_id, None)
        if not is_replay and s.is_sub_agent:
            s.finish_status_tool_call(e.tool_call_id)
            cmds.extend(self._spinner_update_commands())
        elif not is_replay and is_sub_agent_tool(e.tool_name):
            self._spinner.finish_sub_agent_tool_call(e.tool_call_id)
            if e.is_error and isinstance(e.ui_extra, SessionIdUIExtra):
                failed_sub_session = self._sessions.get(e.ui_extra.session_id)
                if failed_sub_session is not None and failed_sub_session.is_sub_agent:
                    failed_sub_session.task_active = False
                    failed_sub_session.clear_status_activity()
            cmds.extend(self._spinner_update_commands())
        elif not is_replay:
            self._spinner.finish_tool_call(e.tool_call_id)
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

    def _handle_TaskMetadataEvent(
        self, e: events.TaskMetadataEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(EndThinkingStream(e.session_id))
        cmds.append(EndAssistantStream(e.session_id))
        cmds.append(RenderTaskMetadata(e))
        return cmds

    def _handle_TaskFileChangeSummaryEvent(
        self, e: events.TaskFileChangeSummaryEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        cmds.append(EndThinkingStream(e.session_id))
        cmds.append(EndAssistantStream(e.session_id))
        cmds.append(RenderTaskFileChangeSummary(e))
        return cmds

    def _handle_UsageEvent(self, e: events.UsageEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        # UsageEvent is not rendered, but it drives context % display.
        if s.is_sub_agent:
            return []
        if not self._is_primary(e.session_id):
            return []
        self._spinner.set_context_usage(e.usage)
        if not is_replay:
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_CacheHitRateEvent(
        self, e: events.CacheHitRateEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if s.is_sub_agent:
            return []
        if not self._is_primary(e.session_id):
            return []
        self._spinner.set_cache_hit_rate(e.cache_hit_rate)
        if not is_replay:
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_StepEndEvent(self, e: events.StepEndEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        return []

    def _handle_TaskFinishEvent(
        self, e: events.TaskFinishEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        s.task_active = False
        s.clear_status_activity()
        cmds.append(RenderTaskFinish(e))
        if s.is_sub_agent:
            parent = self._sessions.get(s.parent_session_id or "")
            parent_session_id = parent.session_id if parent is not None and parent.is_sub_agent else None
            cmds.append(PrintBlankLine(session_id=parent_session_id))

        # Defensive: finalize any open streams so buffered markdown is flushed.
        if s.thinking_stream_active:
            s.thinking_stream_active = False
            cmds.append(EndThinkingStream(session_id=e.session_id))
        if s.assistant_stream_active:
            s.assistant_stream_active = False
            cmds.append(EndAssistantStream(session_id=e.session_id))

        # Rare providers / edge cases may complete a step without emitting any
        # assistant deltas (or without the display consuming them). In that case,
        # fall back to rendering the final task result to avoid a "blank" step.
        if (
            not is_replay
            and not s.is_sub_agent
            and s.assistant_char_count == 0
            and e.task_result.strip()
            and not is_cancelled_task_result(e.task_result)
        ):
            cmds.append(StartAssistantStream(session_id=e.session_id))
            cmds.append(AppendAssistant(session_id=e.session_id, content=e.task_result))
            cmds.append(EndAssistantStream(session_id=e.session_id))

        if not s.is_sub_agent and not is_replay:
            cmds.append(TaskClockClear())
            self._spinner.clear_task_state()
            cmds.append(SpinnerStop())
            cmds.append(StopTitleBlink())
            self._terminal_title_prefix = None if is_cancelled_task_result(e.task_result) else "✅"
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

    def _handle_InterruptEvent(
        self, e: events.InterruptEvent, *, is_replay: bool, s: _SessionState
    ) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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
            cmds.append(RenderInterrupt())
        if not s.is_sub_agent:
            self._skip_next_user_message_rule = True
        return cmds

    def _handle_ErrorEvent(self, e: events.ErrorEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
        if not e.can_retry:
            s.task_active = False
            s.clear_status_activity()
        cmds.append(RenderError(e))
        if not is_replay and not e.can_retry:
            self._spinner.clear_task_state()
            cmds.append(SpinnerStop())
            if not s.is_sub_agent:
                cmds.append(TaskClockClear())
                cmds.append(StopTitleBlink())
                self._terminal_title_prefix = "❌"
                cmds.append(
                    UpdateTerminalTitlePrefix(
                        prefix=self._terminal_title_prefix,
                        model_name=self._model_name,
                        session_title=self._session_title,
                    )
                )
                self._clear_active_sub_agent_sessions()
        if not is_replay:
            cmds.extend(self._spinner_update_commands())
        return cmds

    def _handle_EndEvent(self, e: events.EndEvent, *, is_replay: bool, s: _SessionState) -> list[RenderCommand]:
        cmds: list[RenderCommand] = []
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


# Event-type -> handler dispatch table (built after class definition to reference methods).
DisplayStateMachine._EVENT_HANDLERS = {
    events.WelcomeEvent: DisplayStateMachine._handle_WelcomeEvent,
    events.WelcomeContextEvent: DisplayStateMachine._handle_WelcomeContextEvent,
    events.UserMessageEvent: DisplayStateMachine._handle_UserMessageEvent,
    events.BashCommandStartEvent: DisplayStateMachine._handle_BashCommandStartEvent,
    events.BashCommandOutputDeltaEvent: DisplayStateMachine._handle_BashCommandOutputDeltaEvent,
    events.BashCommandEndEvent: DisplayStateMachine._handle_BashCommandEndEvent,
    events.TaskStartEvent: DisplayStateMachine._handle_TaskStartEvent,
    events.CompactionStartEvent: DisplayStateMachine._handle_CompactionStartEvent,
    events.CompactionEndEvent: DisplayStateMachine._handle_CompactionEndEvent,
    events.ForkCacheHitRateEvent: DisplayStateMachine._handle_ForkCacheHitRateEvent,
    events.RewindEvent: DisplayStateMachine._handle_RewindEvent,
    events.DeveloperMessageEvent: DisplayStateMachine._handle_DeveloperMessageEvent,
    events.SessionTitleChangedEvent: DisplayStateMachine._handle_SessionTitleChangedEvent,
    events.NoticeEvent: DisplayStateMachine._handle_NoticeEvent,
    events.AwaySummaryEvent: DisplayStateMachine._handle_AwaySummaryEvent,
    events.AwaySummaryStartEvent: DisplayStateMachine._handle_AwaySummaryStartEvent,
    events.AwaySummaryEndEvent: DisplayStateMachine._handle_AwaySummaryEndEvent,
    events.SessionStatsEvent: DisplayStateMachine._handle_SessionStatsEvent,
    events.ModelChangedEvent: DisplayStateMachine._handle_ModelChangedEvent,
    events.ThinkingChangedEvent: DisplayStateMachine._handle_ThinkingChangedEvent,
    events.SubAgentModelChangedEvent: DisplayStateMachine._handle_SubAgentModelChangedEvent,
    events.CompactModelChangedEvent: DisplayStateMachine._handle_CompactModelChangedEvent,
    events.FallbackModelConfigWarnEvent: DisplayStateMachine._handle_FallbackModelConfigWarnEvent,
    events.OperationRejectedEvent: DisplayStateMachine._handle_OperationRejectedEvent,
    events.StepStartEvent: DisplayStateMachine._handle_StepStartEvent,
    events.ThinkingStartEvent: DisplayStateMachine._handle_ThinkingStartEvent,
    events.ThinkingDeltaEvent: DisplayStateMachine._handle_ThinkingDeltaEvent,
    events.ThinkingEndEvent: DisplayStateMachine._handle_ThinkingEndEvent,
    events.AssistantTextStartEvent: DisplayStateMachine._handle_AssistantTextStartEvent,
    events.AssistantTextDeltaEvent: DisplayStateMachine._handle_AssistantTextDeltaEvent,
    events.AssistantTextEndEvent: DisplayStateMachine._handle_AssistantTextEndEvent,
    events.ResponseCompleteEvent: DisplayStateMachine._handle_ResponseCompleteEvent,
    events.ToolCallStartEvent: DisplayStateMachine._handle_ToolCallStartEvent,
    events.ToolCallEvent: DisplayStateMachine._handle_ToolCallEvent,
    events.ToolLongRunningEvent: DisplayStateMachine._handle_ToolLongRunningEvent,
    events.ToolOutputDeltaEvent: DisplayStateMachine._handle_ToolOutputDeltaEvent,
    events.ToolResultEvent: DisplayStateMachine._handle_ToolResultEvent,
    events.TaskMetadataEvent: DisplayStateMachine._handle_TaskMetadataEvent,
    events.TaskFileChangeSummaryEvent: DisplayStateMachine._handle_TaskFileChangeSummaryEvent,
    events.UsageEvent: DisplayStateMachine._handle_UsageEvent,
    events.CacheHitRateEvent: DisplayStateMachine._handle_CacheHitRateEvent,
    events.StepEndEvent: DisplayStateMachine._handle_StepEndEvent,
    events.TaskFinishEvent: DisplayStateMachine._handle_TaskFinishEvent,
    events.InterruptEvent: DisplayStateMachine._handle_InterruptEvent,
    events.ErrorEvent: DisplayStateMachine._handle_ErrorEvent,
    events.EndEvent: DisplayStateMachine._handle_EndEvent,
}
