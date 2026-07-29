from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, cast

import pytest

from klaude_code.agent.agent import Agent
from klaude_code.agent.task import MetadataAccumulator, SessionContext, TaskExecutionContext, TaskExecutor
from klaude_code.protocol import events, message
from klaude_code.protocol.models import TaskMetadata, TaskMetadataItem, Usage
from klaude_code.session.session import Session
from klaude_code.session.store_registry import close_default_store
from klaude_code.tool.core.context import build_todo_context


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


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


def test_task_interrupt_does_not_emit_task_file_change_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.file_change_summary.record_edited(str(project_dir / "changed.py"))
        session.file_change_summary.add_diff(added=3, removed=1, path=str(project_dir / "changed.py"))
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

        emitted = executor.on_interrupt()
        await session.wait_for_flush()

        assert not any(isinstance(event, events.TaskFileChangeSummaryEvent) for event in emitted)
        loaded = Session.load(session.id, work_dir=project_dir)
        assert not any(isinstance(item, message.TaskFileChangeSummaryEntry) for item in loaded.conversation_history)
        assert loaded.file_change_summary.diff_lines_added == 3
        assert loaded.file_change_summary.diff_lines_removed == 1
        await close_default_store()

    arun(_test())


def test_task_interrupt_persists_and_emits_partial_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
        accumulator = MetadataAccumulator(model_name="test-model")
        accumulator.add(Usage(input_tokens=100, output_tokens=20, input_cost=0.01))
        sub_agent_metadata = TaskMetadata(
            model_name="sub-agent-model",
            usage=Usage(input_tokens=50, output_tokens=10),
        )
        executor._metadata_accumulator = accumulator  # pyright: ignore[reportPrivateUsage]
        executor._started_at = 1.0  # pyright: ignore[reportPrivateUsage]

        class _StubStep:
            def on_interrupt(self) -> list[events.Event]:
                return [
                    events.ToolResultEvent(
                        session_id=session.id,
                        tool_call_id="agent-call",
                        tool_name="Agent",
                        result="cancelled",
                        status="aborted",
                        task_metadata=sub_agent_metadata,
                    )
                ]

        executor._current_step = cast(Any, _StubStep())  # pyright: ignore[reportPrivateUsage]

        emitted = executor.on_interrupt()
        await session.wait_for_flush()

        metadata_events = [event for event in emitted if isinstance(event, events.TaskMetadataEvent)]
        assert len(metadata_events) == 1
        assert metadata_events[0].is_partial is True
        assert metadata_events[0].metadata.is_partial is True
        assert metadata_events[0].metadata.sub_agent_task_metadata == [sub_agent_metadata]
        loaded = Session.load(session.id, work_dir=project_dir)
        metadata_items = [item for item in loaded.conversation_history if isinstance(item, TaskMetadataItem)]
        assert len(metadata_items) == 1
        metadata = metadata_items[0]
        assert metadata.is_partial is True
        assert metadata.main_agent.usage is not None
        assert metadata.main_agent.usage.input_tokens == 100
        assert metadata.main_agent.usage.output_tokens == 20
        assert metadata.main_agent.usage.input_cost == 0.01
        assert metadata.sub_agent_task_metadata == [sub_agent_metadata]
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

        class _StubStep:
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

        executor._current_step = cast(Any, _StubStep())  # pyright: ignore[reportPrivateUsage]

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

        class _StubStep:
            @property
            def should_show_interrupt_notice(self) -> bool:
                return False

            def on_interrupt(self) -> list[object]:
                return []

        executor._current_step = cast(Any, _StubStep())  # pyright: ignore[reportPrivateUsage]
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


def _make_agent(session: Session) -> Agent:
    # Agent.__init__ only touches the profile when session.model_name is unset.
    session.model_name = "test-model"
    return Agent(session=session, profile=cast(Any, object()))


def test_agent_retracts_unanswered_user_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("retry me"))])
        agent = _make_agent(session)
        agent._last_interrupt_prefill_text = "retry me"  # pyright: ignore[reportPrivateUsage]

        assert agent.retract_interrupted_user_message() == "retry me"
        await session.wait_for_flush()

        assert session.user_messages == []
        assert any(isinstance(item, message.RetractEntry) for item in session.conversation_history)
        # The prefill stays armed for the frontend to restore into its input box.
        assert agent.consume_interrupt_prefill_text() == "retry me"

        loaded = Session.load(session.id, work_dir=project_dir)
        assert loaded.user_messages == []
        await close_default_store()

    arun(_test())


def test_agent_retracts_a_message_with_images_and_prefill_keeps_the_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Images ride in the text as ``[image path]`` markers (extracted again on
    the next submit), so restoring the exact text restores the images too."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        text_with_marker = "check [image /tmp/shot.png]"
        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(
                    parts=[
                        message.TextPart(text=text_with_marker),
                        message.ImageFilePart(file_path="/tmp/shot.png", mime_type="image/png"),
                    ]
                ),
            ]
        )
        agent = _make_agent(session)
        agent._last_interrupt_prefill_text = text_with_marker  # pyright: ignore[reportPrivateUsage]

        assert agent.retract_interrupted_user_message() == text_with_marker
        assert session.user_messages == []
        assert agent.consume_interrupt_prefill_text() == text_with_marker
        await close_default_store()

    arun(_test())


def test_agent_retraction_skipped_when_follow_ups_are_queued(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The TUI drops the prefill when queued messages run next; retracting
    would then lose the message entirely, so it must stay in history."""
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("retry me"))])
        agent = _make_agent(session)
        agent.follow_up(message.UserInputPayload(text="queued"))
        agent._last_interrupt_prefill_text = "retry me"  # pyright: ignore[reportPrivateUsage]

        assert agent.retract_interrupted_user_message() is None
        assert session.user_messages == ["retry me"]
        assert not any(isinstance(item, message.RetractEntry) for item in session.conversation_history)
        await close_default_store()

    arun(_test())


def test_agent_retraction_skipped_after_visible_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project_dir = tmp_path / "test_project"
    project_dir.mkdir()
    monkeypatch.chdir(project_dir)

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("answered"))])
        agent = _make_agent(session)
        # Visible output happened: on_interrupt left the prefill unset.

        assert agent.retract_interrupted_user_message() is None
        assert session.user_messages == ["answered"]
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

        class _StubStep:
            @property
            def should_show_interrupt_notice(self) -> bool:
                return False

            def on_interrupt(self) -> list[object]:
                return []

        executor._current_step = cast(Any, _StubStep())  # pyright: ignore[reportPrivateUsage]
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
