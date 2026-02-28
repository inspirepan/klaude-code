from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.tui.commands import AppendAssistant, EndAssistantStream, StartAssistantStream
from klaude_code.tui.machine import DisplayStateMachine


def test_task_finish_renders_final_result_when_no_assistant_events() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="Hello from task finish",
            has_structured_output=False,
        )
    )

    assert any(isinstance(c, StartAssistantStream) for c in cmds)
    assert any(isinstance(c, AppendAssistant) for c in cmds)
    assert any(isinstance(c, EndAssistantStream) for c in cmds)


def test_task_finish_does_not_duplicate_when_assistant_text_streamed() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    _ = m.transition(events.AssistantTextStartEvent(session_id=session_id, response_id="r1"))
    _ = m.transition(events.AssistantTextDeltaEvent(session_id=session_id, response_id="r1", content="Hi"))
    _ = m.transition(events.AssistantTextEndEvent(session_id=session_id, response_id="r1"))

    cmds = m.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="Hi",
            has_structured_output=False,
        )
    )

    assert not any(isinstance(c, AppendAssistant) for c in cmds)


def test_task_finish_does_not_render_structured_output_as_assistant_text() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result='{"ok": true}',
            has_structured_output=True,
        )
    )

    assert not any(isinstance(c, AppendAssistant) for c in cmds)


def test_task_finish_does_not_render_task_cancelled_as_assistant_text() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="task cancelled",
            has_structured_output=False,
        )
    )

    assert not any(isinstance(c, StartAssistantStream) for c in cmds)
    assert not any(isinstance(c, AppendAssistant) for c in cmds)
    assert not any(isinstance(c, EndAssistantStream) for c in cmds)


def test_task_start_updates_primary_session_after_session_change() -> None:
    m = DisplayStateMachine()

    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    # Simulate session id change (e.g. /new), then ensure primary routing follows it.
    _ = m.transition(events.TaskStartEvent(session_id="s2", model_id="test-model"))

    cmds = m.transition(events.AssistantTextStartEvent(session_id="s2", response_id="r2"))
    assert any(isinstance(c, StartAssistantStream) for c in cmds)
