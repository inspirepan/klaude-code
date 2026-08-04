"""Mid-run transcript rebuilds from the display event tape.

Covers the three pillars of the running Ctrl+O toggle:
- the tape records (and coalesces) exactly what the display consumed;
- a rebuild reconstructs machine state identical to the live pass, so live
  events continue seamlessly afterwards;
- open streams at the tape tail keep their buffers and render their stabilized
  prefix into the rebuild payload.
"""

from __future__ import annotations

import asyncio
from typing import Any

from klaude_code.control.event_tape import EventTape, apply_retractions
from klaude_code.protocol import events, llm_param
from klaude_code.protocol.models import SubAgentState
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail

from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def _welcome(session_id: str) -> events.WelcomeEvent:
    return events.WelcomeEvent(
        session_id=session_id,
        work_dir="/tmp",
        llm_config=llm_param.LLMConfigParameter(
            protocol=llm_param.LLMClientProtocol.OPENAI,
            model_id="test-model",
        ),
    )


# ---------------------------------------------------------------------------
# EventTape
# ---------------------------------------------------------------------------


def test_tape_merges_consecutive_deltas_of_one_stream() -> None:
    tape = EventTape()
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="Hello, "))
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="world"))
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="!"))

    items = tape.snapshot()
    assert len(items) == 1
    merged = items[0]
    assert isinstance(merged, events.AssistantTextDeltaEvent)
    assert merged.content == "Hello, world!"


def test_tape_does_not_merge_across_other_events_or_kinds() -> None:
    tape = EventTape()
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="a"))
    tape.record(events.ThinkingDeltaEvent(session_id="s1", content="t"))
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="b"))
    tape.record(events.UserMessageEvent(session_id="s1", content="msg"))
    tape.record(events.AssistantTextDeltaEvent(session_id="s1", content="c"))

    kinds = [type(item).__name__ for item in tape.snapshot()]
    assert kinds == [
        "AssistantTextDeltaEvent",
        "ThinkingDeltaEvent",
        "AssistantTextDeltaEvent",
        "UserMessageEvent",
        "AssistantTextDeltaEvent",
    ]


def test_tape_truncates_when_the_session_changes() -> None:
    tape = EventTape()
    tape.record(_welcome("s1"))
    tape.record(events.UserMessageEvent(session_id="s1", content="old session"))
    tape.record(_welcome("s2"))
    tape.record(events.UserMessageEvent(session_id="s2", content="new session"))

    items = tape.snapshot()
    assert [type(item).__name__ for item in items] == ["WelcomeEvent", "UserMessageEvent"]
    assert items[0].session_id == "s2"


def test_tape_flattens_replay_history() -> None:
    tape = EventTape()
    tape.record(_welcome("s1"))
    tape.record(
        events.ReplayHistoryEvent(
            session_id="s1",
            updated_at=0.0,
            events=[
                events.UserMessageEvent(session_id="s1", content="from history"),
                events.TaskStartEvent(session_id="s1", model_id="test-model"),
            ],
        )
    )

    kinds = [type(item).__name__ for item in tape.snapshot()]
    assert kinds == ["WelcomeEvent", "UserMessageEvent", "TaskStartEvent"]


# ---------------------------------------------------------------------------
# apply_retractions: render-time view with retracted turns hidden
# ---------------------------------------------------------------------------


def test_apply_retractions_hides_the_whole_retracted_turn() -> None:
    items: list[events.Event] = [
        _welcome("s1"),
        events.UserMessageEvent(session_id="s1", content="answered"),
        events.AssistantTextDeltaEvent(session_id="s1", content="reply"),
        events.UserMessageEvent(session_id="s1", content="retract me"),
        events.TaskStartEvent(session_id="s1", model_id="test-model"),
        events.ThinkingDeltaEvent(session_id="s1", content="pondering"),
        events.InterruptEvent(session_id="s1", show_notice=False),
        events.UserMessageRetractedEvent(session_id="s1", content="retract me"),
        events.TaskFinishEvent(session_id="s1", task_result="task cancelled"),
    ]

    kinds = [type(item).__name__ for item in apply_retractions(items)]
    assert kinds == [
        "WelcomeEvent",
        "UserMessageEvent",
        "AssistantTextDeltaEvent",
        "TaskFinishEvent",
    ]


def test_apply_retractions_targets_the_nearest_matching_message() -> None:
    items: list[events.Event] = [
        events.UserMessageEvent(session_id="s1", content="same text"),
        events.AssistantTextDeltaEvent(session_id="s1", content="answered"),
        events.UserMessageEvent(session_id="s1", content="same text"),
        events.UserMessageRetractedEvent(session_id="s1", content="same text"),
    ]

    filtered = apply_retractions(items)
    kinds = [type(item).__name__ for item in filtered]
    assert kinds == ["UserMessageEvent", "AssistantTextDeltaEvent"]


def test_apply_retractions_without_anchor_hides_nothing() -> None:
    items: list[events.Event] = [
        events.UserMessageEvent(session_id="s1", content="still here"),
        events.UserMessageRetractedEvent(session_id="s1", content="never on tape"),
    ]

    kinds = [type(item).__name__ for item in apply_retractions(items)]
    assert kinds == ["UserMessageEvent"]


# ---------------------------------------------------------------------------
# Machine state invariant: half live + rebuild + half live == all live
# ---------------------------------------------------------------------------


def _mid_run_events() -> list[events.Event]:
    return [
        events.TaskStartEvent(session_id="s1", model_id="test-model", timestamp=100.0),
        events.StepStartEvent(session_id="s1", timestamp=100.5),
        events.ThinkingStartEvent(session_id="s1", timestamp=101.0),
        events.ThinkingDeltaEvent(session_id="s1", content="pondering", timestamp=101.5),
        events.ThinkingEndEvent(session_id="s1", timestamp=102.0),
        events.ToolCallStartEvent(session_id="s1", tool_call_id="t1", tool_name="Read", timestamp=103.0),
        events.ToolCallEvent(
            session_id="s1", tool_call_id="t1", tool_name="Read", arguments='{"file_path": "x.py"}', timestamp=103.5
        ),
        events.AssistantTextStartEvent(session_id="s1", timestamp=104.0),
        events.AssistantTextDeltaEvent(session_id="s1", content="Alpha done.\n\nBeta partial", timestamp=104.5),
    ]


def test_rebuild_reconstructs_live_machine_state() -> None:
    seq = _mid_run_events()

    live = DisplayStateMachine(detail=TranscriptDetail(Detail.COMPACT))
    for event in seq:
        live.transition(event)

    rebuilt = DisplayStateMachine(detail=TranscriptDetail(Detail.COMPACT))
    for event in seq:
        rebuilt.transition(event)
    rebuilt.begin_rebuild()
    for event in seq:
        rebuilt.transition_rebuild(event)

    assert rebuilt._sessions == live._sessions  # pyright: ignore[reportPrivateUsage]
    assert rebuilt._primary_session_id == live._primary_session_id  # pyright: ignore[reportPrivateUsage]
    live_activity = live._spinner.get_activity_text()  # pyright: ignore[reportPrivateUsage]
    rebuilt_activity = rebuilt._spinner.get_activity_text()  # pyright: ignore[reportPrivateUsage]
    assert (rebuilt_activity.plain if rebuilt_activity else None) == (live_activity.plain if live_activity else None)


def test_rebuild_at_the_other_detail_reconstructs_state_too() -> None:
    seq = _mid_run_events()

    detail = TranscriptDetail(Detail.COMPACT)
    machine = DisplayStateMachine(detail=detail)
    for event in seq:
        machine.transition(event)

    detail.set(Detail.FULL)
    machine.begin_rebuild()
    for event in seq:
        machine.transition_rebuild(event)

    reference = DisplayStateMachine(detail=TranscriptDetail(Detail.FULL))
    for event in seq:
        reference.transition(event)

    assert machine._sessions == reference._sessions  # pyright: ignore[reportPrivateUsage]


def test_end_rebuild_restarts_spinner_only_while_running() -> None:
    machine = DisplayStateMachine(detail=TranscriptDetail(Detail.COMPACT))
    machine.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    machine.begin_rebuild()
    machine.transition_rebuild(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    running_cmds = machine.end_rebuild()
    assert any(type(cmd).__name__ == "SpinnerStart" for cmd in running_cmds)

    machine.transition_rebuild(events.TaskFinishEvent(session_id="s1", task_result="done"))
    idle_cmds = machine.end_rebuild()
    assert [type(cmd).__name__ for cmd in idle_cmds] == ["SpinnerStop"]


def test_end_rebuild_drops_dangling_tasks_from_persisted_history() -> None:
    """A history killed mid-turn (e.g. server reload --force) replays a
    TaskStart — including a sub-agent's — with no terminal event. Persisted-
    history replays must clear those danglers or the spinner and the
    sub-agent status row stick around forever."""
    machine = DisplayStateMachine(detail=TranscriptDetail(Detail.COMPACT))
    machine.begin_rebuild()
    machine.transition_rebuild(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    machine.transition_rebuild(
        events.TaskStartEvent(
            session_id="sub1",
            model_id="test-model",
            sub_agent_state=SubAgentState(sub_agent_type="finder", sub_agent_desc="find", sub_agent_prompt="find"),
            parent_session_id="s1",
        )
    )
    cmds = machine.end_rebuild(drop_dangling_tasks=True)
    assert [type(cmd).__name__ for cmd in cmds] == ["SpinnerStop"]

    # Toggle/refresh repaints replay the display tape, which does include a
    # genuinely live turn: those must keep the spinner running.
    machine.begin_rebuild()
    machine.transition_rebuild(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    live_cmds = machine.end_rebuild()
    assert any(type(cmd).__name__ == "SpinnerStart" for cmd in live_cmds)


# ---------------------------------------------------------------------------
# Display-level mid-run toggle
# ---------------------------------------------------------------------------


def test_toggle_mid_run_reveals_thinking_and_keeps_open_stream(monkeypatch: Any) -> None:
    async def _test() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        sid = "s1"

        await display.consume_envelope(make_envelope(_welcome(sid)))
        await display.consume_envelope(make_envelope(events.UserMessageEvent(session_id=sid, content="question")))
        await display.consume_envelope(make_envelope(events.TaskStartEvent(session_id=sid, model_id="test-model")))
        await display.consume_envelope(make_envelope(events.ThinkingStartEvent(session_id=sid)))
        await display.consume_envelope(
            make_envelope(events.ThinkingDeltaEvent(session_id=sid, content="deep secret thought"))
        )
        await display.consume_envelope(make_envelope(events.ThinkingEndEvent(session_id=sid)))
        await display.consume_envelope(make_envelope(events.AssistantTextStartEvent(session_id=sid)))
        await display.consume_envelope(
            make_envelope(events.AssistantTextDeltaEvent(session_id=sid, content="Alpha block done.\n\nBeta partial"))
        )

        await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id=sid)))

        assert display.transcript_detail is Detail.FULL
        payload, clear_screen = writes[-1]
        assert clear_screen is True
        # Full detail rebuild reveals the thinking block compact mode dropped.
        assert "deep secret thought" in payload
        # The completed markdown block of the open stream is stabilized into
        # scrollback; the incomplete tail block stays live-buffered.
        assert "Alpha block done." in payload
        assert "Beta partial" not in payload

        # The open assistant stream survives the rebuild and keeps its buffer,
        # so live deltas continue it without losing the prefix.
        stream = display._renderer._assistant_stream  # pyright: ignore[reportPrivateUsage]
        assert stream.is_active
        assert stream.buffer == "Alpha block done.\n\nBeta partial"

        await display.consume_envelope(
            make_envelope(events.AssistantTextDeltaEvent(session_id=sid, content=" continues"))
        )
        assert stream.buffer == "Alpha block done.\n\nBeta partial continues"

    asyncio.run(_test())


def test_toggle_back_to_compact_hides_thinking_again(monkeypatch: Any) -> None:
    async def _test() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        sid = "s1"

        await display.consume_envelope(make_envelope(_welcome(sid)))
        await display.consume_envelope(make_envelope(events.TaskStartEvent(session_id=sid, model_id="test-model")))
        await display.consume_envelope(make_envelope(events.ThinkingStartEvent(session_id=sid)))
        await display.consume_envelope(
            make_envelope(events.ThinkingDeltaEvent(session_id=sid, content="deep secret thought"))
        )
        await display.consume_envelope(make_envelope(events.ThinkingEndEvent(session_id=sid)))

        await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id=sid)))
        assert "deep secret thought" in writes[-1][0]

        await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id=sid)))
        assert display.transcript_detail is Detail.COMPACT
        assert "deep secret thought" not in writes[-1][0]

    asyncio.run(_test())


def test_retraction_repaints_without_the_withdrawn_turn(monkeypatch: Any) -> None:
    async def _test() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        sid = "s1"

        await display.consume_envelope(make_envelope(_welcome(sid)))
        await display.consume_envelope(make_envelope(events.UserMessageEvent(session_id=sid, content="answered")))
        await display.consume_envelope(
            make_envelope(events.AssistantTextDeltaEvent(session_id=sid, content="reply.\n\n"))
        )
        await display.consume_envelope(make_envelope(events.UserMessageEvent(session_id=sid, content="retract me")))
        await display.consume_envelope(make_envelope(events.TaskStartEvent(session_id=sid, model_id="test-model")))
        await display.consume_envelope(make_envelope(events.InterruptEvent(session_id=sid, show_notice=False)))

        await display.consume_envelope(
            make_envelope(events.UserMessageRetractedEvent(session_id=sid, content="retract me"))
        )

        payload, clear_screen = writes[-1]
        assert clear_screen is True
        assert "retract me" not in payload
        assert "answered" in payload

        # The marker stays on the tape, so later rebuilds keep hiding the turn.
        await display.consume_envelope(make_envelope(events.ToggleTranscriptDetailEvent(session_id=sid)))
        assert "retract me" not in writes[-1][0]

    asyncio.run(_test())
