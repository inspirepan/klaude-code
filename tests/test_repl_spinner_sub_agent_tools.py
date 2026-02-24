from __future__ import annotations

from rich.cells import cell_len

from klaude_code.const import STATUS_DEFAULT_TEXT
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
    assert cell_len(status.plain) == cell_len(STATUS_DEFAULT_TEXT)
    assert status.plain.startswith("Typing")


def test_composing_status_keeps_min_loading_width() -> None:
    state = SpinnerStatusState()
    state.set_composing(True)

    status = state.get_status()
    assert status.plain.startswith("Typing …")
    assert cell_len(status.plain) == cell_len(STATUS_DEFAULT_TEXT)
