from __future__ import annotations

from rich.cells import cell_len

from klaude_code.const import STATUS_DEFAULT_TEXT, STATUS_THINKING_TEXT
from klaude_code.protocol import model
from klaude_code.tui.machine import SpinnerStatusState


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
    state.add_sub_agent_tool_call("tc_1", "Exploring")
    state.add_sub_agent_tool_call("tc_2", "Exploring")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Exploring" in activity.plain
    assert "x 2" in activity.plain

    state.finish_sub_agent_tool_call("tc_1", "Exploring")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Exploring" in activity.plain
    assert "x 2" not in activity.plain


def test_todo_status_takes_priority_over_default_thinking() -> None:
    state = SpinnerStatusState()
    state.set_todo_status("Write tests")
    state.set_reasoning_status("Thinking …")

    todo_status = state.get_todo_status()
    status = state.get_status()
    assert todo_status.plain == "Write tests"
    assert status.plain.startswith("Thinking …")


def test_custom_reasoning_is_shown_on_second_line_when_todo_present() -> None:
    state = SpinnerStatusState()
    state.set_todo_status("Implement feature")
    state.set_reasoning_status("Plan")

    todo_status = state.get_todo_status()
    status = state.get_status()
    assert todo_status.plain == "Implement feature"
    assert status.plain.startswith("Plan")


def test_activity_moves_to_separate_status_line_when_base_present() -> None:
    state = SpinnerStatusState()
    state.set_todo_status("Implement feature")
    state.add_tool_call("Exploring")

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == "Implement feature"
    assert status.plain.startswith("Exploring")


def test_activity_is_shown_on_secondary_line_when_no_base_status() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == ""
    assert status.plain.startswith("Typing …")


def test_short_reasoning_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Typing")

    status = state.get_status()
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)
    assert status.plain.startswith("Typing")


def test_reasoning_on_first_line_and_default_on_secondary_line() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Thinking …")

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == ""
    assert status.plain.startswith("Thinking …")


def test_composing_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == ""
    assert status.plain.startswith("Typing …")
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)


def test_default_status_keeps_min_thinking_width() -> None:
    state = SpinnerStatusState()

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == ""
    assert status.plain.startswith(STATUS_DEFAULT_TEXT)
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)


def test_toast_is_shown_on_secondary_line_with_highest_priority() -> None:
    state = SpinnerStatusState()
    state.set_todo_status("Implement feature")
    state.add_tool_call("Exploring")
    state.set_toast_status("Press ctrl+c again to exit")

    todo_status = state.get_todo_status()
    status = state.get_status()

    assert todo_status.plain == "Implement feature"
    assert status.plain == "Press ctrl+c again to exit"


def test_right_text_shows_context_limit_format() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
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
        model.Usage(
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


def test_right_text_shows_cost_when_available() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
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
        model.Usage(
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
        model.Usage(
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
        model.Usage(
            context_size=46_000,
            context_limit=300_000,
            max_tokens=100_000,
        )
    )
    right_text = state.get_right_text()
    assert right_text is not None
    assert "46k/200k (23.0%)" in right_text.plain

    state.set_context_usage(model.Usage())
    right_text = state.get_right_text()
    assert right_text is not None
    assert "46k/200k (23.0%)" in right_text.plain
