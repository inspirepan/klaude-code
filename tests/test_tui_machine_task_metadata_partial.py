from __future__ import annotations

from klaude_code.protocol import events, model
from klaude_code.tui.commands import PrintBlankLine
from klaude_code.tui.machine import DisplayStateMachine


def test_task_metadata_partial_adds_trailing_blank_line() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    mt = model.TaskMetadataItem(main_agent=model.TaskMetadata(model_name="test"))
    cmds = m.transition(events.TaskMetadataEvent(session_id=session_id, metadata=mt, is_partial=True))

    assert any(isinstance(c, PrintBlankLine) for c in cmds)


def test_task_metadata_final_does_not_add_trailing_blank_line() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    mt = model.TaskMetadataItem(main_agent=model.TaskMetadata(model_name="test"))
    cmds = m.transition(events.TaskMetadataEvent(session_id=session_id, metadata=mt))

    assert not any(isinstance(c, PrintBlankLine) for c in cmds)
