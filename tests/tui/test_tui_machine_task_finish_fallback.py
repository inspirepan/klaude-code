from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.tui.commands import (
    AppendAssistant,
    EndAssistantStream,
    PrintBlankLine,
    StartAssistantStream,
)
from klaude_code.tui.machine import DisplayStateMachine


def test_task_finish_renders_final_result_when_no_assistant_events() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="Hello from task finish",
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
        )
    )

    assert not any(isinstance(c, StartAssistantStream) for c in cmds)
    assert not any(isinstance(c, AppendAssistant) for c in cmds)
    assert not any(isinstance(c, EndAssistantStream) for c in cmds)


def test_foreign_top_level_task_start_does_not_take_over_primary_session() -> None:
    m = DisplayStateMachine()

    _ = m.transition(events.TaskStartEvent(session_id="s1", model_id="test-model"))
    # A peer's turn leaking into this stream must not become the main transcript;
    # session switches (/new) arrive as WelcomeEvent instead.
    assert m.transition(events.TaskStartEvent(session_id="s2", model_id="test-model")) == []
    assert m.transition(events.UserMessageEvent(session_id="s2", content="peer input")) == []

    cmds = m.transition(events.AssistantTextStartEvent(session_id="s2", response_id="r2"))
    assert not any(isinstance(c, StartAssistantStream) for c in cmds)
    cmds = m.transition(events.AssistantTextStartEvent(session_id="s1", response_id="r1"))
    assert any(isinstance(c, StartAssistantStream) for c in cmds)


def test_task_finish_does_not_render_user_message_gap() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(events.TaskFinishEvent(session_id=session_id, task_result="done"))

    assert not any(isinstance(c, PrintBlankLine) for c in cmds)
