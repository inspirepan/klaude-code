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

    status = state.get_status()
    assert status.plain == "Write tests"


def test_custom_reasoning_is_shown_as_activity_when_todo_present() -> None:
    state = SpinnerStatusState()
    state.set_todo_status("Implement feature")
    state.set_reasoning_status("Plan")

    status = state.get_status()
    assert status.plain == "Implement feature | Plan"


def test_short_reasoning_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_reasoning_status("Typing")

    status = state.get_status()
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)
    assert status.plain.startswith("Typing")


def test_composing_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    status = state.get_status()
    assert status.plain.startswith("Typing …")
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)


def test_default_status_keeps_min_thinking_width() -> None:
    state = SpinnerStatusState()

    status = state.get_status()
    assert status.plain.startswith(STATUS_DEFAULT_TEXT)
    assert cell_len(status.plain) == cell_len(STATUS_THINKING_TEXT)


def test_right_text_shows_context_limit_format() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            image_tokens=300,
            context_size=46_000,
            context_limit=300_000,
            max_tokens=100_000,
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("↑10k ◎20k ↓10k ∿2k ▣300 · 46k/200k (23.0%)")


def test_right_text_tokens_accumulate_across_usage_events() -> None:
    state = SpinnerStatusState()
    state.set_context_usage(
        model.Usage(
            input_tokens=30_000,
            cached_tokens=20_000,
            output_tokens=12_000,
            reasoning_tokens=2_000,
            image_tokens=300,
        )
    )
    state.set_context_usage(
        model.Usage(
            input_tokens=11_000,
            cached_tokens=1_000,
            output_tokens=7_000,
            reasoning_tokens=2_000,
            image_tokens=700,
        )
    )

    right_text = state.get_right_text()
    assert right_text is not None
    assert right_text.plain.startswith("↑20k ◎21k ↓15k ∿4k ▣1k")


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
