from datetime import datetime
from pathlib import Path

import pytest

from klaude_code.protocol import events, message
from klaude_code.protocol.models import TaskMetadataItem
from klaude_code.session.session import Session


def _at(seconds: int) -> datetime:
    return datetime.fromtimestamp(seconds)


def _assistant(text: str, seconds: int) -> message.AssistantMessage:
    return message.AssistantMessage(parts=message.text_parts_from_str(text), created_at=_at(seconds))


def _parent(tmp_path: Path, child: Session, monkeypatch: pytest.MonkeyPatch) -> Session:
    def load(cls: type[Session], id: str, work_dir: Path) -> Session:
        assert id == child.id
        return child

    monkeypatch.setattr(Session, "load", classmethod(load))
    return Session(
        id="parent",
        work_dir=tmp_path,
        created_at=100,
        conversation_history=[
            message.UserMessage(parts=message.text_parts_from_str("start"), created_at=_at(100)),
            message.SpawnSubAgentEntry(
                session_id=child.id, sub_agent_type="finder", sub_agent_desc="find", created_at=_at(101)
            ),
            _assistant("parent still working", 103),
            _assistant("parent done", 110),
            TaskMetadataItem(created_at=_at(111)),
        ],
    )


def test_child_result_is_interleaved_at_completion_instead_of_launch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    child = Session(
        id="child",
        work_dir=tmp_path,
        created_at=101,
        conversation_history=[
            _assistant("child working", 102),
            _assistant("child done", 105),
            TaskMetadataItem(created_at=_at(106)),
        ],
    )
    replay = list(_parent(tmp_path, child, monkeypatch).get_history_item())
    text = [event.content for event in replay if isinstance(event, events.AssistantTextDeltaEvent)]
    assert text == ["child working", "parent still working", "child done", "parent done"]
    finish = next(
        i for i, event in enumerate(replay) if isinstance(event, events.TaskFinishEvent) and event.session_id == "child"
    )
    before = next(
        i
        for i, event in enumerate(replay)
        if isinstance(event, events.AssistantTextDeltaEvent) and event.content == "parent still working"
    )
    after = next(
        i
        for i, event in enumerate(replay)
        if isinstance(event, events.AssistantTextDeltaEvent) and event.content == "parent done"
    )
    assert before < finish < after


@pytest.mark.parametrize("tail", ["none", "partial", "background"])
def test_old_completion_does_not_finish_child_continuation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tail: str
) -> None:
    history: list[message.HistoryEvent] = [
        _assistant("first done", 102),
        TaskMetadataItem(created_at=_at(103)),
        message.UserMessage(parts=message.text_parts_from_str("continue"), created_at=_at(104)),
        _assistant("second still working", 105),
    ]
    if tail != "none":
        history.append(
            TaskMetadataItem(
                created_at=_at(106),
                is_partial=tail == "partial",
                background_task_id="nested" if tail == "background" else None,
            )
        )
    child = Session(id="child", work_dir=tmp_path, created_at=101, conversation_history=history)
    replay = list(_parent(tmp_path, child, monkeypatch).get_history_item())
    assert [
        event.task_result
        for event in replay
        if isinstance(event, events.TaskFinishEvent) and event.session_id == "child"
    ] == ["first done"]
