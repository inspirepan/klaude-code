"""`SideQuestionEntry` replay: sidecar entries must not swallow the next step."""

from __future__ import annotations

from pathlib import Path

import pytest

from klaude_code.protocol import events, message
from klaude_code.session.codec import decode_jsonl_line, encode_jsonl_line
from klaude_code.session.session import Session


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


def test_side_question_entry_survives_a_jsonl_roundtrip() -> None:
    entry = message.SideQuestionEntry(question="why cached?", answer="because the prefix matches")

    decoded = decode_jsonl_line(encode_jsonl_line(entry))

    assert isinstance(decoded, message.SideQuestionEntry)
    assert decoded.question == "why cached?"
    assert decoded.answer == "because the prefix matches"


def test_replay_emits_the_side_question_event_and_keeps_the_following_step(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("implement it")),
        message.AssistantMessage(
            parts=[message.ToolCallPart(call_id="call-1", tool_name="Read", arguments_json="{}")],
            response_id=None,
        ),
        message.ToolResultMessage(call_id="call-1", tool_name="Read", output_text="ok", status="success"),
        message.SideQuestionEntry(question="why cached?", answer="because X"),
        message.AssistantMessage(parts=message.text_parts_from_str("done"), response_id=None),
    ]

    replayed = list(session.get_history_item(emit_finish=False))

    side_question_events = [e for e in replayed if isinstance(e, events.SideQuestionEvent)]
    assert len(side_question_events) == 1
    assert side_question_events[0].question == "why cached?"
    assert side_question_events[0].answer == "because X"
    assert side_question_events[0].request_id == ""

    # An assistant message right after the sidecar entry still opens a step.
    step_starts = [e for e in replayed if isinstance(e, events.StepStartEvent)]
    assert len(step_starts) == 2
