"""Replay after a retraction must still close completed turns.

A retracted turn leaves only its InterruptEntry in loaded history (the
UserMessage is projected out at load time). The stale interrupt flag used to
leak across the turn boundary and suppress the next completed turn's
TaskFinishEvent — a dangling TaskStart that revived the spinner ("Loading…")
on every tape rebuild (resize / Ctrl+O) of an idle session.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from klaude_code.protocol import events, message
from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem
from klaude_code.session.session import Session


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


def _metadata_item() -> TaskMetadataItem:
    return TaskMetadataItem(main_agent=TaskMetadata(model_name="test-model"))


def _completed_turn(text: str) -> list[message.HistoryEvent]:
    return [
        message.UserMessage(parts=message.text_parts_from_str(text)),
        message.AssistantMessage(parts=message.text_parts_from_str(f"answer to {text}"), response_id=None),
        _metadata_item(),
    ]


def _task_event_balance(items: list[events.ReplayEventUnion]) -> tuple[int, int]:
    starts = sum(1 for it in items if isinstance(it, events.TaskStartEvent))
    terminals = sum(1 for it in items if isinstance(it, events.TaskFinishEvent | events.InterruptEvent))
    return starts, terminals


def test_retract_between_turns_does_not_swallow_next_task_finish(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        *_completed_turn("first"),
        # Retracted turn: only the interrupt marker survives history loading.
        message.InterruptEntry(show_notice=False),
        *_completed_turn("second"),
    ]

    items = list(session.get_history_item())

    finishes = [it for it in items if isinstance(it, events.TaskFinishEvent)]
    assert len(finishes) == 2
    assert finishes[-1].task_result == "answer to second"
    starts, terminals = _task_event_balance(items)
    assert terminals >= starts


def test_retract_on_first_turn_does_not_swallow_next_task_finish(tmp_path: Path) -> None:
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.InterruptEntry(show_notice=False),
        *_completed_turn("only"),
    ]

    items = list(session.get_history_item())

    finishes = [it for it in items if isinstance(it, events.TaskFinishEvent)]
    assert len(finishes) == 1
    assert finishes[-1].task_result == "answer to only"


def test_interrupted_turn_still_replays_without_synthetic_finish(tmp_path: Path) -> None:
    """The flag's original purpose stays intact: an interrupted turn ends with
    its InterruptEvent, not a synthetic TaskFinishEvent."""
    session = Session(work_dir=tmp_path)
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("start")),
        message.AssistantMessage(parts=message.text_parts_from_str("partial"), response_id=None),
        message.InterruptEntry(show_notice=True),
        _metadata_item(),
    ]

    items = list(session.get_history_item())

    assert not any(isinstance(it, events.TaskFinishEvent) for it in items)
    assert any(isinstance(it, events.InterruptEvent) for it in items)
