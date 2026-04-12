from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.agent.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.protocol import message
from klaude_code.session.session import Session, close_default_store
from klaude_code.tool.context import build_todo_context


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


def test_task_interrupt_persists_interrupt_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
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

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                sub_agent_state=None,
            )
        )

        _ = executor.on_interrupt()
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        assert any(isinstance(item, message.InterruptEntry) for item in loaded.conversation_history)
        await close_default_store()

    arun(_test())


def test_task_interrupt_does_not_duplicate_when_aborted_message_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
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

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                sub_agent_state=None,
            )
        )

        class _StubTurn:
            def on_interrupt(self) -> list[object]:
                session.append_history(
                    [
                        message.AssistantMessage(
                            parts=[],
                            stop_reason="aborted",
                        )
                    ]
                )
                return []

        executor._current_turn = cast(Any, _StubTurn())  # pyright: ignore[reportPrivateUsage]

        _ = executor.on_interrupt()
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        interrupt_entries = [item for item in loaded.conversation_history if isinstance(item, message.InterruptEntry)]
        aborted_assistant = [
            item
            for item in loaded.conversation_history
            if isinstance(item, message.AssistantMessage) and item.stop_reason == "aborted"
        ]
        assert aborted_assistant
        assert not interrupt_entries
        await close_default_store()

    arun(_test())


def test_task_interrupt_without_visible_output_restores_input_and_hides_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
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

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                sub_agent_state=None,
            )
        )

        class _StubTurn:
            @property
            def should_show_interrupt_notice(self) -> bool:
                return False

            def on_interrupt(self) -> list[object]:
                return []

        executor._current_turn = cast(Any, _StubTurn())  # pyright: ignore[reportPrivateUsage]
        executor._current_user_input_text = "retry me"  # pyright: ignore[reportPrivateUsage]

        _ = executor.on_interrupt()
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        interrupt_entries = [item for item in loaded.conversation_history if isinstance(item, message.InterruptEntry)]
        assert len(interrupt_entries) == 1
        assert interrupt_entries[0].show_notice is False
        assert executor.last_interrupt_show_notice is False
        assert executor.take_interrupt_prefill_text() == "retry me"
        assert executor.take_interrupt_prefill_text() is None
        await close_default_store()

    arun(_test())


def test_task_interrupt_after_visible_output_keeps_notice_and_does_not_restore_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
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

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                sub_agent_state=None,
            )
        )

        class _StubTurn:
            @property
            def should_show_interrupt_notice(self) -> bool:
                return False

            def on_interrupt(self) -> list[object]:
                return []

        executor._current_turn = cast(Any, _StubTurn())  # pyright: ignore[reportPrivateUsage]
        executor._current_user_input_text = "retry me"  # pyright: ignore[reportPrivateUsage]
        executor._task_visible_output_started = True  # pyright: ignore[reportPrivateUsage]

        _ = executor.on_interrupt()
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        interrupt_entries = [item for item in loaded.conversation_history if isinstance(item, message.InterruptEntry)]
        assert len(interrupt_entries) == 1
        assert interrupt_entries[0].show_notice is True
        assert executor.last_interrupt_show_notice is True
        assert executor.take_interrupt_prefill_text() is None
        await close_default_store()

    arun(_test())
