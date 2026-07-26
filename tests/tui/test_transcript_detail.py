"""Tests for the transcript detail aspect itself.

The point of `tui.transcript_detail` is that one table answers "does this event
reach the transcript", and both the state machine and the renderer ask it rather
than re-deriving the answer. These tests pin that down: the table's own shape,
that each of the two layers consults it, and that the shared holder keeps the two
layers from drifting apart.
"""

from __future__ import annotations

import pytest

from klaude_code.protocol import events, message
from klaude_code.protocol.models import SubAgentState
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import (
    EVERY_QUADRANT,
    Detail,
    Quadrant,
    TranscriptDetail,
    hidden_in,
    is_visible,
    listed_event_types,
)

_SUB_AGENT_STATE = SubAgentState(
    sub_agent_type="finder",
    sub_agent_desc="inspect replay",
    sub_agent_prompt="Read every relevant file",
)


def test_quadrant_of_covers_every_combination() -> None:
    seen = {Quadrant.of(detail, is_sub_agent=is_sub_agent) for detail in Detail for is_sub_agent in (False, True)}
    assert seen == EVERY_QUADRANT


def test_detail_toggle_round_trips() -> None:
    holder = TranscriptDetail()
    assert holder.current is Detail.COMPACT
    assert holder.is_compact

    assert holder.toggle() is Detail.FULL
    assert not holder.is_compact
    assert holder.toggle() is Detail.COMPACT


def test_unlisted_event_is_visible_everywhere() -> None:
    event = events.UserMessageEvent(session_id="s", content="hi")
    assert hidden_in(type(event)) == frozenset()
    for detail in Detail:
        for is_sub_agent in (False, True):
            assert is_visible(event, detail=detail, is_sub_agent=is_sub_agent)


@pytest.mark.parametrize(
    ("event", "expected_hidden"),
    [
        (
            events.NoticeEvent(session_id="s", content="note"),
            {Quadrant.COMPACT_SUB_AGENT},
        ),
        (
            events.ToolCallEvent(session_id="s", tool_call_id="c", tool_name="Read", arguments="{}"),
            {Quadrant.COMPACT_SUB_AGENT},
        ),
        (
            events.TaskStartEvent(session_id="s", sub_agent_state=_SUB_AGENT_STATE),
            EVERY_QUADRANT - {Quadrant.FULL_SUB_AGENT},
        ),
        (
            events.TaskFinishEvent(session_id="s", task_result="done"),
            EVERY_QUADRANT - {Quadrant.FULL_SUB_AGENT},
        ),
        (
            events.TaskFileChangeSummaryEvent(
                session_id="s",
                summary=message.TaskFileChangeSummaryEntry(files=[]),
            ),
            {Quadrant.COMPACT_SUB_AGENT, Quadrant.FULL_SUB_AGENT},
        ),
    ],
)
def test_is_visible_matches_the_table(event: events.Event, expected_hidden: set[Quadrant]) -> None:
    assert hidden_in(type(event)) == expected_hidden
    for detail in Detail:
        for is_sub_agent in (False, True):
            quadrant = Quadrant.of(detail, is_sub_agent=is_sub_agent)
            assert is_visible(event, detail=detail, is_sub_agent=is_sub_agent) is (quadrant not in expected_hidden)


def test_table_entries_are_neither_empty_nor_total() -> None:
    """An empty set means the entry never fires; a full set means stop emitting it."""
    assert listed_event_types()
    for event_cls in listed_event_types():
        quadrants = hidden_in(event_cls)
        assert quadrants, event_cls.__name__
        assert quadrants != EVERY_QUADRANT, event_cls.__name__


def _register_sub_agent(renderer: TUICommandRenderer, session_id: str) -> None:
    renderer.register_session(session_id, _SUB_AGENT_STATE)


@pytest.mark.parametrize("detail", list(Detail))
def test_renderer_asks_the_table_for_sub_agent_notices(detail: Detail) -> None:
    renderer = TUICommandRenderer()
    renderer.set_transcript_detail(detail)
    _register_sub_agent(renderer, "child")

    with renderer.bulk_render_capture() as captured:
        renderer.display_notice(events.NoticeEvent(session_id="child", content="sub-agent note"))

    expected = is_visible(
        events.NoticeEvent(session_id="child", content="sub-agent note"),
        detail=detail,
        is_sub_agent=True,
    )
    assert ("sub-agent note" in captured.getvalue()) is expected


def test_machine_asks_the_table_for_sub_agent_compaction_summaries() -> None:
    """The compaction summary reaches the renderer as a bare string, so the
    machine is the layer that has to consult the table."""

    def summaries(detail: Detail) -> int:
        machine = DisplayStateMachine()
        machine.set_transcript_detail(detail)
        machine.transition(events.TaskStartEvent(session_id="child", sub_agent_state=_SUB_AGENT_STATE))
        cmds = machine.transition(
            events.CompactionEndEvent(session_id="child", reason="threshold", summary="<summary>gist</summary>")
        )
        return sum(1 for cmd in cmds if type(cmd).__name__ == "RenderCompactionSummary")

    assert summaries(Detail.COMPACT) == 0
    assert summaries(Detail.FULL) == 1


def test_display_shares_one_holder_between_machine_and_renderer() -> None:
    display = TUIDisplay()
    assert display.transcript_detail is Detail.COMPACT

    display._detail.toggle()  # pyright: ignore[reportPrivateUsage]  # what the ToggleTranscriptDetailEvent handler flips

    assert display.transcript_detail is Detail.FULL
    assert display.compact_transcript is False
    # Same object, so neither layer can be left behind on a toggle.
    assert display._machine._detail is display._renderer._detail  # pyright: ignore[reportPrivateUsage]
    assert display._machine._detail.current is Detail.FULL  # pyright: ignore[reportPrivateUsage]
