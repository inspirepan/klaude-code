from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from klaude_code.const import STATUS_COMPACTING_TEXT, STATUS_DEFAULT_TEXT, STATUS_HANDOFF_TEXT
from klaude_code.protocol.events import CompactionStartEvent
from klaude_code.protocol.models import Usage
from klaude_code.tui.commands import SpinnerUpdate
from klaude_code.tui.machine import STATUS_LEFT_MIN_WIDTH_CELLS, DisplayStateMachine, SpinnerStatusState


def test_sub_agent_tool_calls_persist_across_turn_start() -> None:
    state = SpinnerStatusState()
    state.add_sub_agent_tool_call("tc_1", "Tasking")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Tasking" in activity.plain

    state.clear_for_new_turn()

    activity = state.get_activity_text()
    assert activity is not None
    assert "Tasking" in activity.plain

    state.finish_sub_agent_tool_call("tc_1", "Tasking")
    assert state.get_activity_text() is None

def test_sub_agent_tool_calls_decrement_by_tool_call_id() -> None:
    state = SpinnerStatusState()
    state.add_sub_agent_tool_call("tc_1", "Finding")
    state.add_sub_agent_tool_call("tc_2", "Finding")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Finding" in activity.plain
    assert "x 2" in activity.plain

    state.finish_sub_agent_tool_call("tc_1", "Finding")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Finding" in activity.plain
    assert "x 2" not in activity.plain

def test_reasoning_status_overrides_default_status() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Thinking…")

    status = state.get_status()
    assert status.plain.startswith("Thinking…")

def test_custom_reasoning_status_is_shown() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Plan")

    status = state.get_status()
    assert status.plain.startswith("Plan")

def test_activity_status_is_shown_when_present() -> None:
    state = SpinnerStatusState()
    state.add_tool_call("Finding")

    status = state.get_status()

    assert status.plain.startswith("Finding")

def test_composing_status_is_shown() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    status = state.get_status()

    assert status.plain.startswith("Typing…")

def test_short_reasoning_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Typing")

    status = state.get_status()
    assert cell_len(status.plain) == STATUS_LEFT_MIN_WIDTH_CELLS
    assert status.plain.startswith("Typing")

def test_thinking_status_is_shown() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Thinking…")

    status = state.get_status()

    assert status.plain.startswith("Thinking…")

def test_clear_default_reasoning_status_keeps_non_thinking_phase() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status(STATUS_COMPACTING_TEXT)

    state.clear_default_reasoning_status()

    status = state.get_status()
    assert status.plain.startswith(STATUS_COMPACTING_TEXT)

def test_handoff_compaction_uses_distinct_spinner_status() -> None:
    machine = DisplayStateMachine()

    cmds = machine.transition(CompactionStartEvent(session_id="s1", reason="handoff"))

    update = next(cmd for cmd in cmds if isinstance(cmd, SpinnerUpdate))
    status_text = update.status_lines[0].text
    plain = status_text.plain if isinstance(status_text, Text) else status_text
    assert plain.startswith(STATUS_HANDOFF_TEXT)

def test_composing_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    status = state.get_status()

    assert status.plain.startswith("Typing…")
    assert cell_len(status.plain) == STATUS_LEFT_MIN_WIDTH_CELLS

def test_stopping_composing_returns_to_default_status() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)
    state.set_buffer_length(123)

    state.set_composing(False)

    status = state.get_status()
    assert status.plain.startswith(STATUS_DEFAULT_TEXT)

def test_default_status_keeps_min_thinking_width() -> None:
    state = SpinnerStatusState()

    status = state.get_status()

    assert status.plain.startswith(STATUS_DEFAULT_TEXT)
    assert cell_len(status.plain) == STATUS_LEFT_MIN_WIDTH_CELLS

def test_toast_has_highest_priority() -> None:
    state = SpinnerStatusState()
    state.add_tool_call("Finding")
    state.set_toast_status("Press ctrl+c again to exit")

    status = state.get_status()

    assert status.plain == "Press ctrl+c again to exit"

def test_right_text_shows_context_limit_format() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            context_size=46_000,
            context_limit=300_000,
            max_tokens=100_000,
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("in 10k · cache 20k · out 10k · thought 2k · 46k/200k (23.0%)")

def test_right_text_shows_cache_hit_rate_next_to_cached_tokens() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            input_cost=0.001,
            output_cost=0.002,
            cache_read_cost=0.0005,
        )
    )
    state.set_cache_hit_rate(0.91)

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("in 10k · cache 20k (91%) · out 10k · thought 2k")

def test_right_text_shows_cache_write_tokens() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            cache_write_tokens=5_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("in 5k · cache 20k · cache+ 5k · out 10k · thought 2k")

def test_right_text_shows_cost_when_available() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            input_cost=0.001,
            output_cost=0.002,
            cache_read_cost=0.0005,
            currency="USD",
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert "cost $0.0035" in right_text.plain

def test_right_text_tokens_accumulate_across_usage_events() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            input_cost=0.001,
            output_cost=0.002,
            cache_read_cost=0.0005,
        )
    )
    state.set_context_usage(
        Usage(
            input_tokens=11_000,
            cached_tokens=1_000,
            output_tokens=7_000,
            reasoning_tokens=2_000,
            input_cost=0.0003,
            output_cost=0.0007,
            cache_read_cost=0.0001,
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("in 20k · cache 21k · out 15k · thought 4k")
    assert "cost $0.0046" in right_text.plain

def test_right_text_keeps_last_context_when_current_usage_has_no_context() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        Usage(
            context_size=46_000,
            context_limit=300_000,
            max_tokens=100_000,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None
    assert "46k/200k (23.0%)" in right_text.plain

    state.set_context_usage(Usage())
    right_text = state.get_right_text()
    assert right_text is not None
    assert "46k/200k (23.0%)" in right_text.plain
