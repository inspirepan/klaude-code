import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from klaude_code.prompts.messages import EMPTY_RESPONSE_CONTINUATION_PROMPT
from klaude_code.prompts.sub_agents import (
    FORK_CONTEXT_GENERAL_PREFIX,
    FORK_CONTEXT_GENERAL_PROMPT,
    FORK_CONTEXT_WITH_ROLE_PREFIX,
)
from klaude_code.protocol import events, message
from klaude_code.protocol.models import SessionIdUIExtra, SubAgentState, TaskMetadataItem
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


@pytest.mark.parametrize("reference", ["spawn", "tool_result"])
def test_fork_replays_only_its_own_children(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reference: str) -> None:
    finder = Session(
        id="finder",
        parent_session_id="parent",
        work_dir=tmp_path,
        created_at=101,
        conversation_history=[_assistant("found it", 102), TaskMetadataItem(created_at=_at(103))],
    )
    inherited: message.HistoryEvent
    if reference == "spawn":
        inherited = message.SpawnSubAgentEntry(
            session_id=finder.id, sub_agent_type="finder", sub_agent_desc="find", created_at=_at(101)
        )
    else:
        inherited = message.ToolResultMessage(
            call_id="launch-finder",
            tool_name="Agent",
            output_text="launched",
            status="success",
            ui_extra=SessionIdUIExtra(session_id=finder.id),
            created_at=_at(101),
        )
    nested = Session(
        id="nested",
        parent_session_id="fork",
        work_dir=tmp_path,
        created_at=105,
        conversation_history=[_assistant("nested done", 106), TaskMetadataItem(created_at=_at(107))],
    )
    fork = Session(
        id="fork",
        parent_session_id="parent",
        work_dir=tmp_path,
        created_at=104,
        conversation_history=[
            inherited.model_copy(deep=True),
            message.SpawnSubAgentEntry(
                session_id=nested.id, sub_agent_type="finder", sub_agent_desc="nested", created_at=_at(105)
            ),
        ],
    )
    parent = Session(
        id="parent",
        work_dir=tmp_path,
        created_at=100,
        conversation_history=[
            inherited,
            message.SpawnSubAgentEntry(
                session_id=fork.id,
                sub_agent_type="general-purpose-fork-context",
                sub_agent_desc="forked work",
                fork_context=True,
                created_at=_at(104),
            ),
        ],
    )
    children = {child.id: child for child in (finder, fork, nested)}

    def load(cls: type[Session], id: str, work_dir: Path) -> Session:
        return children[id]

    monkeypatch.setattr(Session, "load", classmethod(load))
    replay = list(parent.get_history_item())
    assert [
        (event.session_id, event.parent_session_id) for event in replay if isinstance(event, events.TaskStartEvent)
    ] == [("parent", None), ("finder", "parent"), ("fork", "parent"), ("nested", "fork")]
    assert [(event.session_id, event.task_result) for event in replay if isinstance(event, events.TaskFinishEvent)] == [
        ("finder", "found it"),
        ("nested", "nested done"),
    ]


def test_legacy_child_without_parent_metadata_still_replays(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    meta_file = Session.paths(tmp_path).meta_file("child")
    meta_file.parent.mkdir(parents=True)
    meta_file.write_text(
        json.dumps(
            {
                "created_at": 101,
                "sub_agent_state": {
                    "sub_agent_type": "finder",
                    "sub_agent_desc": "legacy find",
                    "sub_agent_prompt": "find",
                },
            }
        )
    )
    child = Session.load_meta("child", work_dir=tmp_path)
    assert child.parent_session_id is None
    child.conversation_history = [_assistant("legacy result", 102), TaskMetadataItem(created_at=_at(103))]
    replay = list(_parent(tmp_path, child, monkeypatch).get_history_item())
    start = next(event for event in replay if isinstance(event, events.TaskStartEvent) and event.session_id == child.id)
    assert start.sub_agent_state is not None
    assert start.sub_agent_state.sub_agent_desc == "legacy find"
    assert start.parent_session_id == "parent"
    assert [
        event.task_result
        for event in replay
        if isinstance(event, events.TaskFinishEvent) and event.session_id == child.id
    ] == ["legacy result"]


def test_top_level_fork_keeps_inherited_child_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    child = Session(
        id="child",
        parent_session_id="parent",
        work_dir=tmp_path,
        created_at=101,
        conversation_history=[_assistant("found it", 102), TaskMetadataItem(created_at=_at(103))],
    )
    parent = _parent(tmp_path, child, monkeypatch)

    async def run() -> None:
        fork = parent.fork(new_id="forked-parent")
        await fork.wait_for_flush()
        assert fork.parent_session_id is None
        assert [
            event.task_result
            for event in fork.get_history_item()
            if isinstance(event, events.TaskFinishEvent) and event.session_id == child.id
        ] == ["found it"]

    asyncio.run(run())


@pytest.mark.parametrize("source", ["peer_message", "shell_completion", None])
def test_injected_messages_do_not_finish_running_turns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, source: message.UserMessageSource | None
) -> None:
    child = Session(
        id="child",
        work_dir=tmp_path,
        created_at=101,
        conversation_history=[
            _assistant("still working", 102),
            message.UserMessage(
                source=source,
                parts=message.text_parts_from_str(EMPTY_RESPONSE_CONTINUATION_PROMPT if source is None else "update"),
                created_at=_at(103),
            ),
            _assistant("first done", 104),
            TaskMetadataItem(created_at=_at(105)),
            message.UserMessage(
                source="peer_message", parts=message.text_parts_from_str("continue"), created_at=_at(106)
            ),
            _assistant("second done", 107),
            TaskMetadataItem(created_at=_at(108)),
        ],
    )
    replay = list(_parent(tmp_path, child, monkeypatch).get_history_item())
    assert [
        event.task_result
        for event in replay
        if isinstance(event, events.TaskFinishEvent) and event.session_id == child.id
    ] == ["first done", "second done"]
    assert (
        len([event for event in replay if isinstance(event, events.TaskStartEvent) and event.session_id == child.id])
        == 2
    )


@pytest.mark.parametrize(
    "reminder",
    [
        FORK_CONTEXT_GENERAL_PROMPT,
        FORK_CONTEXT_GENERAL_PREFIX + "Legacy guidance.",
        FORK_CONTEXT_WITH_ROLE_PREFIX + "Role.",
    ],
)
@pytest.mark.parametrize("legacy_meta", [False, True])
def test_fork_context_replays_after_its_own_identity_reminder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reminder: str, legacy_meta: bool
) -> None:
    child = Session(
        id="child",
        parent_session_id=None if legacy_meta else "parent",
        sub_agent_state=SubAgentState(
            sub_agent_type="general-purpose-fork-context",
            sub_agent_desc="legacy fork",
            sub_agent_prompt="child task",
            fork_context=True,
        )
        if legacy_meta
        else None,
        work_dir=tmp_path,
        created_at=101,
        conversation_history=[
            message.UserMessage(
                parts=message.text_parts_from_str(f"<system-reminder>{FORK_CONTEXT_GENERAL_PROMPT}</system-reminder>"),
                created_at=_at(98),
            ),
            message.UserMessage(parts=message.text_parts_from_str("inherited task"), created_at=_at(99)),
            _assistant("inherited result", 100),
            TaskMetadataItem(created_at=_at(100)),
            message.UserMessage(
                parts=message.text_parts_from_str(f"<system-reminder>{reminder}</system-reminder>"),
                created_at=_at(101),
            ),
            message.UserMessage(parts=message.text_parts_from_str("child task"), created_at=_at(102)),
            _assistant("own result", 105),
            TaskMetadataItem(created_at=_at(106)),
        ],
    )
    replay = [
        event for event in _parent(tmp_path, child, monkeypatch).get_history_item() if event.session_id == child.id
    ]
    assert [event.content for event in replay if isinstance(event, events.AssistantTextDeltaEvent)] == ["own result"]
    assert [event.task_result for event in replay if isinstance(event, events.TaskFinishEvent)] == ["own result"]
    starts = [event for event in replay if isinstance(event, events.TaskStartEvent)]
    assert len(starts) == 1
    assert starts[0].sub_agent_state is not None
    assert starts[0].sub_agent_state.sub_agent_prompt == "child task"
    assert any(
        isinstance(item, message.AssistantMessage) and message.join_text_parts(item.parts) == "inherited result"
        for item in child.get_llm_history()
    )
