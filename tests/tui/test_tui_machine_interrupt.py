from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.protocol.models import Usage
from klaude_code.tui.commands import EndAssistantStream, EndThinkingStream, PrintBlankLine, RenderInterrupt
from klaude_code.tui.machine import DisplayStateMachine


def test_replay_interrupt_has_blank_lines_around_render() -> None:
    m = DisplayStateMachine()

    cmds = m.transition_replay(events.InterruptEvent(session_id="s1"))

    assert isinstance(cmds[0], EndThinkingStream)
    assert isinstance(cmds[1], EndAssistantStream)
    assert isinstance(cmds[2], RenderInterrupt)
    assert not any(isinstance(cmd, PrintBlankLine) for cmd in cmds)


def test_interrupt_without_notice_skips_render_interrupt() -> None:
    m = DisplayStateMachine()

    cmds = m.transition_replay(events.InterruptEvent(session_id="s1", show_notice=False))

    assert isinstance(cmds[0], EndThinkingStream)
    assert isinstance(cmds[1], EndAssistantStream)
    assert not any(isinstance(cmd, RenderInterrupt) for cmd in cmds)


def test_interrupt_preserves_accumulated_usage() -> None:
    m = DisplayStateMachine()
    session_id = "s1"
    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    _ = m.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=Usage(input_tokens=100, output_tokens=20, input_cost=0.01),
        )
    )

    _ = m.transition(events.InterruptEvent(session_id=session_id))

    assert m._spinner._token_input == 100  # pyright: ignore[reportPrivateUsage]
    assert m._spinner._token_output == 20  # pyright: ignore[reportPrivateUsage]
    assert m._spinner._cost_total == 0.01  # pyright: ignore[reportPrivateUsage]
