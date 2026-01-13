from __future__ import annotations

from klaude_code.protocol import events
from klaude_code.tui.commands import AppendAssistant, EndAssistantStream, StartAssistantStream
from klaude_code.tui.machine import DisplayStateMachine


def test_response_complete_renders_final_content_when_no_deltas() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    cmds = m.transition(
        events.ResponseCompleteEvent(
            session_id=session_id,
            response_id="r1",
            content="Hello\n\nWorld",
        )
    )

    start_i = next(i for i, c in enumerate(cmds) if isinstance(c, StartAssistantStream))
    append_i = next(i for i, c in enumerate(cmds) if isinstance(c, AppendAssistant))
    end_i = next(i for i, c in enumerate(cmds) if isinstance(c, EndAssistantStream))

    assert start_i < append_i < end_i
    assert cmds[append_i].content == "Hello\n\nWorld"  # type: ignore[attr-defined]


def test_response_complete_does_not_duplicate_when_streaming_happened() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    _ = m.transition(events.AssistantTextStartEvent(session_id=session_id, response_id="r1"))
    _ = m.transition(events.AssistantTextDeltaEvent(session_id=session_id, response_id="r1", content="Hi"))
    _ = m.transition(events.AssistantTextEndEvent(session_id=session_id, response_id="r1"))

    cmds = m.transition(
        events.ResponseCompleteEvent(
            session_id=session_id,
            response_id="r1",
            content="Hi",
        )
    )

    assert not any(isinstance(c, AppendAssistant) for c in cmds)


def test_response_complete_finalizes_unended_assistant_stream() -> None:
    m = DisplayStateMachine()
    session_id = "s1"

    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    _ = m.transition(events.AssistantTextStartEvent(session_id=session_id, response_id="r1"))
    _ = m.transition(events.AssistantTextDeltaEvent(session_id=session_id, response_id="r1", content="Hi"))

    cmds = m.transition(
        events.ResponseCompleteEvent(
            session_id=session_id,
            response_id="r1",
            content="Hi",
        )
    )

    assert any(isinstance(c, EndAssistantStream) for c in cmds)