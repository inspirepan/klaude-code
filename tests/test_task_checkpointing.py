from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import klaude_code.core.task as task_module
from klaude_code.core.agent_profile import AgentProfile
from klaude_code.core.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.core.tool.context import build_todo_context
from klaude_code.protocol import events, message
from klaude_code.session.session import Session, close_default_store


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


def _build_profile() -> AgentProfile:
    llm_config = SimpleNamespace(model_id="test-model")
    llm_client = SimpleNamespace(model_name="test-model", get_llm_config=lambda: llm_config)
    return AgentProfile(llm_client=cast(Any, llm_client), system_prompt=None, tools=[], reminders=[])


def _build_executor(
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    task_finished_sequence: list[bool],
    continue_agent_sequence: list[bool] | None = None,
) -> tuple[TaskExecutor, Any]:
    def _never_compact(*, session: Session, config: Any, llm_config: Any) -> bool:
        del session, config, llm_config
        return False

    monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)

    class StubTurnExecutor:
        created_count = 0

        def __init__(self, _: Any) -> None:
            index = type(self).created_count
            type(self).created_count += 1
            self.task_finished = task_finished_sequence[index]
            if continue_agent_sequence is None:
                self.continue_agent = True
            else:
                self.continue_agent = continue_agent_sequence[index]
            self.task_result = "done"
            self.has_structured_output = False

        async def run(self) -> AsyncGenerator[events.Event]:
            if False:
                yield cast(events.Event, None)

    monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

    async def _process_reminder(_: Any) -> AsyncGenerator[events.DeveloperMessageEvent]:
        if False:
            yield cast(events.DeveloperMessageEvent, None)

    session_ctx = SessionContext(
        session_id=session.id,
        get_conversation_history=session.get_llm_history,
        append_history=session.append_history,
        file_tracker=session.file_tracker,
        todo_context=build_todo_context(session),
        run_subtask=None,
        request_user_interaction=None,
    )
    executor = TaskExecutor(
        TaskExecutionContext(
            session=session,
            session_ctx=session_ctx,
            profile=_build_profile(),
            tool_registry={},
            process_reminder=_process_reminder,
            sub_agent_state=None,
        )
    )
    return executor, StubTurnExecutor


def test_run_with_user_input_creates_single_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        executor, _ = _build_executor(session, monkeypatch, [True])

        _ = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        assert session.n_checkpoints == 1
        await close_default_store()

    arun(_test())


def test_multi_turn_task_still_creates_one_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        executor, stub_turn = _build_executor(session, monkeypatch, [False, True])

        _ = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        assert stub_turn.created_count == 2
        assert session.n_checkpoints == 1
        await close_default_store()

    arun(_test())


def test_continue_with_empty_input_does_not_create_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        executor, _ = _build_executor(session, monkeypatch, [True])

        _ = [event async for event in executor.run(message.UserInputPayload(text="   "))]

        assert session.n_checkpoints == 0
        await close_default_store()

    arun(_test())


def test_task_metadata_marked_partial_when_continue_agent_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        executor, _ = _build_executor(
            session,
            monkeypatch,
            task_finished_sequence=[True],
            continue_agent_sequence=[False],
        )

        run_events = [event async for event in executor.run(message.UserInputPayload(text="hello"))]
        task_metadata_events = [event for event in run_events if isinstance(event, events.TaskMetadataEvent)]

        assert len(task_metadata_events) == 1
        assert task_metadata_events[0].is_partial is True
        await close_default_store()

    arun(_test())
