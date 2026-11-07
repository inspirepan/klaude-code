from __future__ import annotations

from datetime import datetime

import pytest

from klaude_code.protocol import events
from klaude_code.protocol.models import SubAgentState, TaskMetadata, TaskMetadataItem
from klaude_code.tui.commands import RenderTaskMetadata, RenderTurnTiming
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail


def _ts(hour: int, minute: int) -> float:
    return datetime.now().replace(hour=hour, minute=minute, second=0, microsecond=0).timestamp()


def _main_turn(start_hour: int, start_minute: int, *, duration_s: float = 120.0) -> tuple[events.Event, events.Event]:
    start = _ts(start_hour, start_minute)
    end = start + duration_s
    task_start = events.TaskStartEvent(session_id="main", model_id="test-model", timestamp=start)
    metadata = events.TaskMetadataEvent(
        session_id="main",
        metadata=TaskMetadataItem(main_agent=TaskMetadata(model_name="test", task_duration_s=duration_s)),
        timestamp=end,
    )
    return task_start, metadata


@pytest.mark.parametrize(
    ("duration_s", "label"),
    [(11.0, "19:10"), (120.0, "19:12"), (3600.0, "20:10"), (3601.0, "19:10 → 20:10")],
)
def test_compact_main_agent_emits_turn_timing_before_metadata(duration_s: float, label: str) -> None:
    machine = DisplayStateMachine()  # compact by default
    task_start, metadata = _main_turn(19, 10, duration_s=duration_s)

    machine.transition(task_start)
    cmds = machine.transition(metadata)

    timing = [cmd for cmd in cmds if isinstance(cmd, RenderTurnTiming)]
    assert len(timing) == 1
    metadata_index = next(i for i, cmd in enumerate(cmds) if isinstance(cmd, RenderTaskMetadata))
    assert cmds.index(timing[0]) < metadata_index
    assert timing[0].label == label
    assert timing[0].duration_s == duration_s


def test_full_mode_does_not_emit_turn_timing() -> None:
    machine = DisplayStateMachine()
    machine.set_transcript_detail(Detail.FULL)
    task_start, metadata = _main_turn(19, 10)

    machine.transition(task_start)
    cmds = machine.transition(metadata)

    assert not any(isinstance(cmd, RenderTurnTiming) for cmd in cmds)


def test_sub_agent_metadata_does_not_emit_turn_timing() -> None:
    machine = DisplayStateMachine()  # compact by default
    start = _ts(19, 10)
    task_start = events.TaskStartEvent(
        session_id="sub",
        sub_agent_state=SubAgentState(
            sub_agent_type="finder",
            sub_agent_desc="finder",
            sub_agent_prompt="prompt",
        ),
        timestamp=start,
    )
    metadata = events.TaskMetadataEvent(
        session_id="sub",
        metadata=TaskMetadataItem(main_agent=TaskMetadata(model_name="test", task_duration_s=120.0)),
        timestamp=start + 120.0,
    )

    machine.transition(task_start)
    cmds = machine.transition(metadata)

    assert not any(isinstance(cmd, RenderTurnTiming) for cmd in cmds)


def test_missing_duration_skips_turn_timing() -> None:
    machine = DisplayStateMachine()
    start = _ts(19, 10)
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model", timestamp=start))
    cmds = machine.transition(
        events.TaskMetadataEvent(
            session_id="main",
            metadata=TaskMetadataItem(main_agent=TaskMetadata(model_name="test")),
            timestamp=start + 60.0,
        )
    )

    assert not any(isinstance(cmd, RenderTurnTiming) for cmd in cmds)


def test_turn_timing_ignores_stale_task_started_at_on_replay() -> None:
    machine = DisplayStateMachine()
    # A replayed persisted-history first TaskStartEvent carries the session
    # creation time, not the turn's actual start; the timing label must not
    # trust it, or the span would contradict the printed duration.
    machine.transition(events.TaskStartEvent(session_id="main", model_id="test-model", timestamp=_ts(8, 59)))
    end = _ts(19, 12)
    cmds = machine.transition(
        events.TaskMetadataEvent(
            session_id="main",
            metadata=TaskMetadataItem(main_agent=TaskMetadata(model_name="test", task_duration_s=3720.0)),
            timestamp=end,
        )
    )

    timing = [cmd for cmd in cmds if isinstance(cmd, RenderTurnTiming)]
    assert len(timing) == 1
    assert timing[0].label == "18:10 → 19:12"


@pytest.mark.parametrize(
    ("duration_s", "label", "duration"),
    [
        (0.0, "19:10", "0s"),
        (11.0, "19:10", "11s"),
        (126.0, "19:12", "2m 6s"),
        (3600.0, "20:10", "1h"),
        (3601.0, "19:10 → 20:10", "1h 1s"),
    ],
)
def test_renderer_keeps_turn_timing_adjacent_to_metadata(duration_s: float, label: str, duration: str) -> None:
    renderer = TUICommandRenderer()
    with renderer.bulk_render_capture() as buf:
        renderer.display_turn_timing(label, duration_s)
        renderer.display_task_metadata(
            events.TaskMetadataEvent(
                session_id="main",
                metadata=TaskMetadataItem(main_agent=TaskMetadata(model_name="test", task_duration_s=duration_s)),
            )
        )
    assert buf.getvalue().startswith(f"  Worked for {duration} · {label}\n• test\n")
