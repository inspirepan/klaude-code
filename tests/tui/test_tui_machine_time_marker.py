from __future__ import annotations

from datetime import datetime, timedelta

from rich.color import Color

from klaude_code.protocol import events
from klaude_code.tui.commands import RenderTimeMarker, RenderUserMessage
from klaude_code.tui.components.rich.theme import DARK_PALETTE, ThemeKey
from klaude_code.tui.machine import DisplayStateMachine, _format_time_marker_label
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail


def _ts(dt: datetime) -> float:
    return dt.timestamp()


def _user_message(ts: float, content: str = "hi") -> events.UserMessageEvent:
    return events.UserMessageEvent(session_id="main", content=content, timestamp=ts)


def _expanded_machine() -> DisplayStateMachine:
    machine = DisplayStateMachine()
    machine.set_transcript_detail(Detail.FULL)
    return machine


def test_first_visible_block_gets_time_marker_in_expanded_mode() -> None:
    machine = _expanded_machine()
    cmds = machine.transition_replay(_user_message(_ts(datetime(2026, 7, 25, 19, 10))))
    assert isinstance(cmds[0], RenderTimeMarker)
    assert any(isinstance(cmd, RenderUserMessage) for cmd in cmds)


def test_time_marker_repeats_only_after_a_new_five_minute_bucket() -> None:
    machine = _expanded_machine()
    base = datetime(2026, 7, 25, 19, 10)

    first = machine.transition_replay(_user_message(_ts(base)))
    assert isinstance(first[0], RenderTimeMarker)

    # Same bucket (19:10-19:15): no new marker.
    within = machine.transition_replay(_user_message(_ts(base + timedelta(minutes=2))))
    assert not any(isinstance(cmd, RenderTimeMarker) for cmd in within)

    # New bucket (19:15-19:20): marker again.
    later = machine.transition_replay(_user_message(_ts(base + timedelta(minutes=5))))
    assert isinstance(later[0], RenderTimeMarker)


def test_compact_mode_never_emits_time_markers() -> None:
    machine = DisplayStateMachine()  # compact by default
    cmds = machine.transition_replay(_user_message(_ts(datetime(2026, 7, 25, 19, 10))))
    assert not any(isinstance(cmd, RenderTimeMarker) for cmd in cmds)


def test_status_only_commands_do_not_trigger_time_markers() -> None:
    machine = _expanded_machine()
    # StepStartEvent yields no commands during replay: no visible block.
    cmds = machine.transition_replay(
        events.StepStartEvent(session_id="main", timestamp=_ts(datetime(2026, 7, 25, 19, 10)))
    )
    assert not any(isinstance(cmd, RenderTimeMarker) for cmd in cmds)
    # The marker state must remain unset so the next visible block still gets one.
    follow_up = machine.transition_replay(_user_message(_ts(datetime(2026, 7, 25, 19, 11))))
    assert isinstance(follow_up[0], RenderTimeMarker)


def test_begin_replay_resets_time_marker_state() -> None:
    machine = _expanded_machine()
    ts = _ts(datetime(2026, 7, 25, 19, 10))
    machine.transition_replay(_user_message(ts))

    machine.begin_replay()
    replayed = machine.transition_replay(_user_message(ts))
    assert isinstance(replayed[0], RenderTimeMarker)


def test_time_marker_label_uses_24h_clock_time_for_today() -> None:
    today_at_1910 = datetime.now().replace(hour=19, minute=10, second=0, microsecond=0)
    assert _format_time_marker_label(_ts(today_at_1910)) == "19:10"


def test_time_marker_label_adds_date_when_not_today() -> None:
    yesterday = datetime.now() - timedelta(days=1)
    ts = _ts(yesterday.replace(hour=19, minute=10, second=0, microsecond=0))
    assert _format_time_marker_label(ts) == yesterday.strftime("%m-%d 19:10")


def test_renderer_outputs_clock_label_followed_by_blank_line() -> None:
    renderer = TUICommandRenderer()
    with renderer.bulk_render_capture() as buf:
        renderer.display_time_marker("19:10")
    assert " ⏱ 19:10 \n\n" in buf.getvalue()
    style = renderer.console.get_style(ThemeKey.TIME_MARKER)
    assert style.color == Color.parse(DARK_PALETTE.magenta)
    assert style.reverse is True
