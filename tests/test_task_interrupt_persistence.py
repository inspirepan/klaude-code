from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.core.task import SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.core.tool.context import build_todo_context
from klaude_code.protocol import message
from klaude_code.session.session import Session, close_default_store


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:  # pyright: ignore[reportUnusedFunction]
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


def test_task_interrupt_persists_interrupt_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session_ctx = SessionContext(
            session_id=session.id,
            get_conversation_history=session.get_llm_history,
            append_history=session.append_history,
            file_tracker=session.file_tracker,
            todo_context=build_todo_context(session),
            run_subtask=None,
            request_user_interaction=None,
        )

        async def _process_reminder(_: Any):
            if False:
                yield

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                process_reminder=_process_reminder,
                sub_agent_state=None,
            )
        )

        _ = executor.on_interrupt()
        await session.wait_for_flush()

        loaded = Session.load(session.id)
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
            get_conversation_history=session.get_llm_history,
            append_history=session.append_history,
            file_tracker=session.file_tracker,
            todo_context=build_todo_context(session),
            run_subtask=None,
            request_user_interaction=None,
        )

        async def _process_reminder(_: Any):
            if False:
                yield

        executor = TaskExecutor(
            TaskExecutionContext(
                session=session,
                session_ctx=session_ctx,
                profile=cast(Any, object()),
                tool_registry={},
                process_reminder=_process_reminder,
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

        loaded = Session.load(session.id)
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
