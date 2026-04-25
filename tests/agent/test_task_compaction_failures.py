from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Coroutine
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import klaude_code.agent.task as task_module
from klaude_code.agent.agent_profile import AgentProfile
from klaude_code.agent.compaction.compaction import CompactionResult
from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.agent.turn import TurnError
from klaude_code.protocol import events, message
from klaude_code.protocol.models import FileStatus, SubAgentState
from klaude_code.session.session import Session
from klaude_code.session.store_registry import close_default_store
from klaude_code.tool.core.context import build_todo_context


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _always_compact(**_: Any) -> bool:
    return True


def _never_compact(**_: Any) -> bool:
    return False


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


def _build_executor(
    session: Session,
    *,
    sub_agent_state: SubAgentState | None = None,
    attachments: list[Any] | None = None,
) -> TaskExecutor:
    llm_config = SimpleNamespace(model_id="test-model")
    llm_client = SimpleNamespace(model_name="test-model", get_llm_config=lambda: llm_config)

    session_ctx = SessionContext(
        session_id=session.id,
        work_dir=session.work_dir,
        get_conversation_history=session.get_llm_history,
        append_history=session.append_history,
        file_tracker=session.file_tracker,
        file_change_summary=session.file_change_summary,
        todo_context=build_todo_context(session),
        run_subtask=None,
        request_user_interaction=None,
    )
    profile = AgentProfile(llm_client=cast(Any, llm_client), system_prompt=None, tools=[], attachments=attachments or [])
    return TaskExecutor(
        TaskExecutionContext(
            session=session,
            session_ctx=session_ctx,
            profile=profile,
            tool_registry={},
            sub_agent_state=sub_agent_state,
        )
    )


def test_threshold_compaction_failure_emits_error_once_per_task(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])

        monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

        compaction_calls = 0

        async def _failing_run_compaction(**_: Any) -> Any:
            nonlocal compaction_calls
            compaction_calls += 1
            raise RuntimeError("compact boom")

        monkeypatch.setattr(task_module, "run_compaction", _failing_run_compaction)

        class StubTurnExecutor:
            created_count = 0

            def __init__(self, _: Any) -> None:
                index = type(self).created_count
                type(self).created_count += 1
                self.task_finished = index >= 1
                self.continue_agent = True
                self.task_result = "done"

            async def run(self) -> AsyncGenerator[events.Event]:
                if False:
                    yield cast(events.Event, None)

        monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

        executor = _build_executor(session)
        collected = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        error_events = [event for event in collected if isinstance(event, events.ErrorEvent)]
        assert compaction_calls == 1
        assert StubTurnExecutor.created_count == 2
        assert len(error_events) == 1
        assert error_events[0].can_retry is True
        assert "Compaction failed, continuing without compaction: compact boom" in error_events[0].error_message
        await close_default_store()

    arun(_test())


def test_threshold_compaction_recollects_attachments_before_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        session.file_tracker[str(project_dir / ".klaude-system-skill-listing")] = FileStatus(
            mtime=0.0,
            is_skill_listing=True,
        )

        monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

        async def _successful_run_compaction(**_: Any) -> CompactionResult:
            return CompactionResult(
                summary="compact summary",
                first_kept_index=0,
                tokens_before=100,
                details=None,
                kept_items_brief=[],
            )

        monkeypatch.setattr(task_module, "run_compaction", _successful_run_compaction)

        attachment_calls = 0

        async def _available_skills_attachment(session_arg: Session) -> message.DeveloperMessage | None:
            nonlocal attachment_calls
            attachment_calls += 1
            if any(status.is_skill_listing for status in session_arg.file_tracker.values()):
                return None
            return message.DeveloperMessage(
                parts=message.text_parts_from_str("<system-reminder>available skills</system-reminder>"),
                attachment_position="prepend",
            )

        histories_seen_by_turn: list[list[message.HistoryEvent]] = []

        class StubTurnExecutor:
            def __init__(self, context: Any) -> None:
                histories_seen_by_turn.append(list(context.session_ctx.get_conversation_history()))
                self.task_finished = True
                self.continue_agent = False
                self.task_result = "done"

            async def run(self) -> AsyncGenerator[events.Event]:
                if False:
                    yield cast(events.Event, None)

        monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

        executor = _build_executor(session, attachments=[_available_skills_attachment])
        collected = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        developer_events = [event for event in collected if isinstance(event, events.DeveloperMessageEvent)]
        assert attachment_calls == 1
        assert len(developer_events) == 1
        assert message.join_text_parts(developer_events[0].item.parts) == (
            "<system-reminder>available skills</system-reminder>"
        )
        assert histories_seen_by_turn
        assert any(
            isinstance(item, message.DeveloperMessage)
            and "available skills" in message.join_text_parts(item.parts)
            for item in histories_seen_by_turn[0]
        )
        assert not any(status.is_skill_listing for status in session.file_tracker.values())
        await close_default_store()

    arun(_test())


def test_threshold_nothing_to_compact_keeps_future_threshold_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])

        monkeypatch.setattr(task_module, "should_compact_threshold", _always_compact)

        compaction_calls = 0

        async def _nothing_to_compact(**_: Any) -> Any:
            nonlocal compaction_calls
            compaction_calls += 1
            raise ValueError("Nothing to compact (session too small)")

        monkeypatch.setattr(task_module, "run_compaction", _nothing_to_compact)

        class StubTurnExecutor:
            created_count = 0

            def __init__(self, _: Any) -> None:
                index = type(self).created_count
                type(self).created_count += 1
                self.task_finished = index >= 1
                self.continue_agent = True
                self.task_result = "done"

            async def run(self) -> AsyncGenerator[events.Event]:
                if False:
                    yield cast(events.Event, None)

        monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

        executor = _build_executor(session)
        collected = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        assert compaction_calls == 2
        assert StubTurnExecutor.created_count == 2
        assert not any(isinstance(event, events.ErrorEvent) for event in collected)
        await close_default_store()

    arun(_test())


def test_overflow_compaction_failure_stops_without_turn_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])

        monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)

        compaction_calls = 0

        async def _failing_run_compaction(**_: Any) -> Any:
            nonlocal compaction_calls
            compaction_calls += 1
            raise RuntimeError("compact boom")

        monkeypatch.setattr(task_module, "run_compaction", _failing_run_compaction)

        class StubTurnExecutor:
            created_count = 0

            def __init__(self, _: Any) -> None:
                type(self).created_count += 1
                self.task_finished = False
                self.continue_agent = True
                self.task_result = ""

            async def run(self) -> AsyncGenerator[events.Event]:
                if False:
                    yield cast(events.Event, None)
                raise TurnError("prompt is too long")

        monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

        executor = _build_executor(session)
        collected = [event async for event in executor.run(message.UserInputPayload(text="hello"))]

        error_events = [event for event in collected if isinstance(event, events.ErrorEvent)]
        assert compaction_calls == 1
        assert StubTurnExecutor.created_count == 1
        assert len(error_events) == 1
        assert error_events[0].can_retry is False
        assert "prompt is too long" in error_events[0].error_message
        assert "Compaction failed while recovering from context overflow: compact boom" in error_events[0].error_message
        assert not any("Retrying" in event.error_message for event in error_events)
        assert not any(isinstance(event, events.TaskFinishEvent) for event in collected)
        await close_default_store()

    arun(_test())


def test_overflow_compaction_failure_raises_for_sub_agents(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)

        monkeypatch.setattr(task_module, "should_compact_threshold", _never_compact)

        compaction_calls = 0

        async def _failing_run_compaction(**_: Any) -> Any:
            nonlocal compaction_calls
            compaction_calls += 1
            raise RuntimeError("compact boom")

        monkeypatch.setattr(task_module, "run_compaction", _failing_run_compaction)

        class StubTurnExecutor:
            created_count = 0

            def __init__(self, _: Any) -> None:
                type(self).created_count += 1
                self.task_finished = False
                self.continue_agent = True
                self.task_result = ""

            async def run(self) -> AsyncGenerator[events.Event]:
                if False:
                    yield cast(events.Event, None)
                raise TurnError("prompt is too long")

        monkeypatch.setattr(task_module, "TurnExecutor", StubTurnExecutor)

        executor = _build_executor(
            session,
            sub_agent_state=SubAgentState(
                sub_agent_type="general-purpose",
                sub_agent_desc="sub task",
                sub_agent_prompt="hello",
                fork_context=False,
            ),
        )

        collected: list[events.Event] = []
        with pytest.raises(
            RuntimeError, match="Compaction failed while recovering from context overflow: compact boom"
        ):
            async for event in executor.run(message.UserInputPayload(text="hello")):
                collected.append(event)

        error_events = [event for event in collected if isinstance(event, events.ErrorEvent)]
        assert compaction_calls == 1
        assert StubTurnExecutor.created_count == 1
        assert len(error_events) == 1
        assert error_events[0].can_retry is False
        assert "prompt is too long" in error_events[0].error_message
        await close_default_store()

    arun(_test())
