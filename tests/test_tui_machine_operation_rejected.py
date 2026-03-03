from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.tui.commands import RenderNotice
from klaude_code.tui.machine import DisplayStateMachine


def test_operation_rejected_event_renders_as_notice() -> None:
    machine = DisplayStateMachine()

    cmds = machine.transition(
        events.OperationRejectedEvent(
            session_id="s1",
            operation_id="op-1",
            operation_type="run_agent",
            reason="session_busy",
            active_task_id="task-1",
        )
    )

    assert len(cmds) == 1
    assert isinstance(cmds[0], RenderNotice)
    assert isinstance(cmds[0].event, events.NoticeEvent)
    assert cmds[0].event.is_error is True
    assert "operation=run_agent" in cmds[0].event.content
    assert "active_task_id=task-1" in cmds[0].event.content
