from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.tui.commands import EndAssistantStream, EndThinkingStream, PrintBlankLine, RenderInterrupt
from klaude_code.tui.machine import DisplayStateMachine


def test_replay_interrupt_has_blank_lines_around_render() -> None:
    m = DisplayStateMachine()

    cmds = m.transition_replay(events.InterruptEvent(session_id="s1"))

    assert isinstance(cmds[0], EndThinkingStream)
    assert isinstance(cmds[1], EndAssistantStream)
    assert isinstance(cmds[2], PrintBlankLine)
    assert isinstance(cmds[3], RenderInterrupt)
    assert isinstance(cmds[4], PrintBlankLine)
