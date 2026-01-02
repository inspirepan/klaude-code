from __future__ import annotations

from klaude_code.ui.modes.repl.event_handler import SpinnerStatusState


def test_sub_agent_tool_calls_persist_across_turn_start() -> None:
    state = SpinnerStatusState()
    state.add_sub_agent_tool_call("tc_1", "Tasking")

    assert state.get_activity_text() is not None
    assert "Tasking" in state.get_activity_text().plain

    state.clear_for_new_turn()

    assert state.get_activity_text() is not None
    assert "Tasking" in state.get_activity_text().plain

    state.finish_sub_agent_tool_call("tc_1", "Tasking")
    assert state.get_activity_text() is None


def test_sub_agent_tool_calls_decrement_by_tool_call_id() -> None:
    state = SpinnerStatusState()
    state.add_sub_agent_tool_call("tc_1", "Exploring")
    state.add_sub_agent_tool_call("tc_2", "Exploring")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Sub" in activity.plain
    assert "Exploring" in activity.plain
    assert "x 2" in activity.plain

    state.finish_sub_agent_tool_call("tc_1", "Exploring")

    activity = state.get_activity_text()
    assert activity is not None
    assert "Exploring" in activity.plain
    assert "x 2" not in activity.plain
