# pyright: reportPrivateUsage=false, reportUnusedFunction=false
import asyncio
import json
import threading
import time
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, NoReturn

import pytest
from typer.testing import CliRunner

from klaude_code.protocol import events, llm_param, message, op
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SessionIdUIExtra,
    SessionRuntimeState,
    SubAgentState,
    TaskMetadata,
    TaskMetadataItem,
    TodoItem,
    Usage,
)
from klaude_code.session.session import Session
from klaude_code.session.store import JsonlSessionWriter, build_meta_snapshot
from klaude_code.session.store_registry import close_default_store


class _ForkSessionDummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> NoReturn:  # pragma: no cover
        raise NotImplementedError


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:  # pyright: ignore[reportUnusedFunction]
    return isolated_home


# =====================
# Tests for session.py
# =====================


class TestSession:
    """Tests for Session class."""

    def test_create_session_with_defaults(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        assert session.id is not None
        assert len(session.id) == 32  # UUID hex format
        assert session.work_dir == tmp_path
        assert session.conversation_history == []
        assert session.todos == []
        assert session.model_name is None

    def test_messages_count_empty(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        assert session.messages_count == 0

    def test_messages_count_with_history(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        history: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("Hello")),
            message.AssistantMessage(parts=message.text_parts_from_str("Hi")),
            message.ToolResultMessage(
                call_id="1",
                tool_name="test",
                status="success",
                output_text="done",
            ),
            message.UserMessage(parts=message.text_parts_from_str("Bye")),
        ]
        session.conversation_history = history
        # Counts user, assistant, and tool result messages
        assert session.messages_count == 4

    def test_messages_count_cached(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        history: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("Hello")),
            message.AssistantMessage(parts=message.text_parts_from_str("Hi")),
        ]
        session.conversation_history = history
        # First access calculates and caches
        count1 = session.messages_count
        assert count1 == 2
        # Second access should use cache
        count2 = session.messages_count
        assert count2 == 2

    def test_invalidate_messages_count_cache(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        history: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("Hello")),
        ]
        session.conversation_history = history
        assert session.messages_count == 1
        session._invalidate_messages_count_cache()
        # Add more messages manually
        session.conversation_history.append(message.UserMessage(parts=message.text_parts_from_str("World")))
        assert session.messages_count == 2


class TestSessionDirectories:
    """Tests for Session directory methods."""

    def test_base_dir_under_home(self, tmp_path: Path):
        base = Session.paths(tmp_path).base_dir
        assert base.parent == Path.home() / ".klaude" / "projects"

    def test_sessions_dir_under_base(self, tmp_path: Path):
        sessions_dir = Session.paths(tmp_path).sessions_dir
        assert sessions_dir.name == "sessions"


class TestSessionNeedTurnStart:
    """Tests for Session.need_turn_start method."""

    def test_turn_start_for_assistant_after_user(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = message.UserMessage(parts=message.text_parts_from_str("Hi"))
        item = message.AssistantMessage(parts=message.text_parts_from_str("Hello"))
        assert session.need_turn_start(prev, item) is True

    def test_turn_start_for_assistant_after_tool_result(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = message.ToolResultMessage(call_id="1", tool_name="Read", status="success", output_text="done")
        item = message.AssistantMessage(parts=message.text_parts_from_str("Thinking..."))
        assert session.need_turn_start(prev, item) is True

    def test_no_turn_start_for_user_message(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = message.AssistantMessage(parts=message.text_parts_from_str("Hello"))
        item = message.UserMessage(parts=message.text_parts_from_str("Hi"))
        assert session.need_turn_start(prev, item) is False

    def test_turn_start_when_prev_none(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        item = message.AssistantMessage(parts=message.text_parts_from_str("Hello"))
        assert session.need_turn_start(None, item) is True

    def test_no_turn_start_for_consecutive_assistant(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        prev = message.AssistantMessage(parts=message.text_parts_from_str("Hello"))
        item = message.AssistantMessage(parts=message.text_parts_from_str("Follow-up"))
        assert session.need_turn_start(prev, item) is False


class TestSessionPersistence:
    """Tests for Session save/load with file system."""

    def test_save_and_load_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # Create a unique project directory
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(
                work_dir=project_dir,
                title="Persisted title",
                model_name="test-model",
                session_state=SessionRuntimeState.RUNNING,
                archived=True,
                model_config_name="test-config-model",
                model_thinking=llm_param.Thinking(reasoning_effort="high"),
            )
            session.todos = [TodoItem(content="Task 1", status="pending")]
            session.file_tracker = {"/path/to/file": FileStatus(mtime=1234567890.0)}
            session.file_change_summary = FileChangeSummary(
                created_files=["/path/to/created"],
                edited_files=["/path/to/edited"],
                deleted_files=["/path/to/deleted"],
                diff_lines_added=5,
                diff_lines_removed=2,
            )
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("persist"))])
            await session.wait_for_flush()

            loaded = Session.load(session.id, work_dir=project_dir)
            assert loaded.id == session.id
            assert loaded.work_dir == project_dir
            assert loaded.title == "Persisted title"
            assert loaded.model_name == "test-model"
            assert loaded.session_state == SessionRuntimeState.RUNNING
            assert loaded.archived is True
            assert loaded.model_config_name == "test-config-model"
            assert loaded.model_thinking is not None
            assert loaded.model_thinking.reasoning_effort == "high"
            assert len(loaded.todos) == 1
            assert loaded.todos[0].content == "Task 1"
            assert "/path/to/file" in loaded.file_tracker
            assert loaded.file_change_summary.created_files == ["/path/to/created"]
            assert loaded.file_change_summary.edited_files == ["/path/to/edited"]
            assert loaded.file_change_summary.deleted_files == ["/path/to/deleted"]
            assert loaded.file_change_summary.diff_lines_added == 5
            assert loaded.file_change_summary.diff_lines_removed == 2
            await close_default_store()

        arun(_test())

    def test_load_meta_does_not_load_messages(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir, model_name="test-model", model_config_name="test-config-model")
            session.session_state = SessionRuntimeState.IDLE
            session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("Hello")),
                    message.AssistantMessage(parts=message.text_parts_from_str("Hi")),
                ]
            )
            await session.wait_for_flush()

            meta = Session.load_meta(session.id, work_dir=project_dir)
            assert meta.id == session.id
            assert meta.model_name == "test-model"
            assert meta.session_state == SessionRuntimeState.IDLE
            assert meta.archived is False
            assert meta.model_config_name == "test-config-model"
            assert len(meta.conversation_history) == 0
            await close_default_store()

        arun(_test())

    def test_append_history_does_not_overwrite_newer_runtime_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        original_write_batch_sync = JsonlSessionWriter._write_batch_sync

        def _slow_write_batch_sync(self: JsonlSessionWriter, batch: Any) -> None:
            time.sleep(0.2)
            original_write_batch_sync(self, batch)

        monkeypatch.setattr(JsonlSessionWriter, "_write_batch_sync", _slow_write_batch_sync)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            meta_path = Session.paths(project_dir).meta_file(session.id)
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(
                json.dumps(
                    build_meta_snapshot(
                        session_id=session.id,
                        work_dir=project_dir,
                        title=session.title,
                        sub_agent_state=session.sub_agent_state,
                        file_tracker=session.file_tracker,
                        file_change_summary=session.file_change_summary,
                        todos=list(session.todos),
                        user_messages=session.user_messages,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                        messages_count=session.messages_count,
                        model_name=session.model_name,
                        session_state=session.session_state,
                        runtime_owner=session.runtime_owner,
                        runtime_owner_heartbeat_at=session.runtime_owner_heartbeat_at,
                        archived=session.archived,
                        model_config_name=session.model_config_name,
                        model_thinking=session.model_thinking,
                        next_checkpoint_id=session.next_checkpoint_id,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Hello"))])

            Session.persist_runtime_state(session.id, SessionRuntimeState.RUNNING, project_dir)

            await session.wait_for_flush()

            loaded = Session.load_meta(session.id, work_dir=project_dir)
            assert loaded.session_state == SessionRuntimeState.RUNNING
            await close_default_store()

        arun(_test())

    def test_append_history_does_not_overwrite_runtime_state_updated_during_meta_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            session.session_state = SessionRuntimeState.RUNNING
            meta_path = Session.paths(project_dir).meta_file(session.id)
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            meta_path.write_text(
                json.dumps(
                    build_meta_snapshot(
                        session_id=session.id,
                        work_dir=project_dir,
                        title=session.title,
                        sub_agent_state=session.sub_agent_state,
                        file_tracker=session.file_tracker,
                        file_change_summary=session.file_change_summary,
                        todos=list(session.todos),
                        user_messages=session.user_messages,
                        created_at=session.created_at,
                        updated_at=session.updated_at,
                        messages_count=session.messages_count,
                        model_name=session.model_name,
                        session_state=session.session_state,
                        runtime_owner=session.runtime_owner,
                        runtime_owner_heartbeat_at=session.runtime_owner_heartbeat_at,
                        archived=session.archived,
                        model_config_name=session.model_config_name,
                        model_thinking=session.model_thinking,
                        next_checkpoint_id=session.next_checkpoint_id,
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            original_read_text = Path.read_text
            update_started = threading.Event()
            update_finished = threading.Event()

            def _read_text(path: Path, *args: Any, **kwargs: Any) -> str:
                text = original_read_text(path, *args, **kwargs)
                if path == meta_path and not update_started.is_set():
                    update_started.set()

                    def _update_runtime_state() -> None:
                        Session.persist_runtime_state(session.id, SessionRuntimeState.IDLE, project_dir)
                        update_finished.set()

                    threading.Thread(target=_update_runtime_state, daemon=True).start()
                    time.sleep(0.05)
                return text

            monkeypatch.setattr(Path, "read_text", _read_text)

            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Hello"))])
            await session.wait_for_flush()

            assert update_started.is_set()
            assert update_finished.wait(timeout=1.0)

            loaded = Session.load_meta(session.id, work_dir=project_dir)
            assert loaded.session_state == SessionRuntimeState.IDLE
            await close_default_store()

        arun(_test())

    def test_load_nonexistent_session_creates_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # Load a session that doesn't exist
        loaded = Session.load("nonexistent123", work_dir=project_dir)
        assert loaded.id == "nonexistent123"
        assert loaded.work_dir == project_dir

    def test_append_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            items = [
                message.UserMessage(parts=message.text_parts_from_str("Hello")),
                message.AssistantMessage(parts=message.text_parts_from_str("Hi there")),
            ]
            session.append_history(items)
            await session.wait_for_flush()

            assert len(session.conversation_history) == 2
            assert session.messages_count == 2

            events_file = Session.paths(project_dir).events_file(session.id)
            assert events_file.exists()

            loaded = Session.load(session.id, work_dir=project_dir)
            assert len(loaded.conversation_history) == 2
            await close_default_store()

        arun(_test())

    def test_replay_includes_sub_agent_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            sub_session = Session.create(id="sub-session", work_dir=project_dir)
            sub_session.append_history(
                [
                    message.AssistantMessage(
                        parts=[
                            message.ToolCallPart(
                                call_id="sub-call",
                                tool_name="Bash",
                                arguments_json="{}",
                            )
                        ]
                    )
                ]
            )
            await sub_session.wait_for_flush()

            main_session = Session.create(id="main-session", work_dir=project_dir)
            main_session.append_history(
                [
                    message.AssistantMessage(
                        parts=[
                            message.ToolCallPart(
                                call_id="parent-call",
                                tool_name="Agent",
                                arguments_json="{}",
                            )
                        ]
                    ),
                    message.ToolResultMessage(
                        call_id="parent-call",
                        tool_name="Agent",
                        output_text="Delegated to sub-agent",
                        status="success",
                        ui_extra=SessionIdUIExtra(session_id=sub_session.id),
                    ),
                ]
            )
            await main_session.wait_for_flush()

            reloaded = Session.load(main_session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())

            parent_call_index = next(
                i
                for i, e in enumerate(events_list)
                if isinstance(e, events.ToolCallEvent) and e.session_id == main_session.id
            )
            parent_result_index = next(
                i
                for i, e in enumerate(events_list)
                if isinstance(e, events.ToolResultEvent) and e.session_id == main_session.id
            )

            sub_events = [e for e in events_list if getattr(e, "session_id", None) == sub_session.id]
            assert sub_events, "Expected sub-agent events to be replayed"

            sub_task_starts = [e for e in sub_events if isinstance(e, events.TaskStartEvent)]
            assert sub_task_starts, "Expected TaskStartEvent from sub-agent"

            sub_tool_calls = [e for e in sub_events if isinstance(e, events.ToolCallEvent)]
            assert sub_tool_calls, "Expected ToolCallEvent from sub-agent"

            first_sub_event_index = min(events_list.index(e) for e in sub_events)
            assert parent_call_index < parent_result_index < first_sub_event_index
            await close_default_store()

        arun(_test())

    def test_replay_sub_agent_task_finish_without_agent_id_footer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            sub_session = Session.create(id="sub-session", work_dir=project_dir)
            sub_session.sub_agent_state = SubAgentState(
                sub_agent_type="Task",
                sub_agent_desc="sub",
                sub_agent_prompt="do something",
            )
            sub_session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("done"))])
            await sub_session.wait_for_flush()

            reloaded = Session.load(sub_session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())
            finish_events = [e for e in events_list if isinstance(e, events.TaskFinishEvent)]
            assert len(finish_events) == 1
            assert finish_events[0].task_result == "done"
            await close_default_store()

        arun(_test())

    def test_spawn_sub_agent_entry_replays_sub_agent_history(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """SpawnSubAgentEntry triggers sub-agent history replay (even without ToolResultMessage)."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            # Create a sub-agent session with a completed task (has TaskMetadataItem)
            sub_session = Session.create(id="spawn-sub", work_dir=project_dir)
            sub_session.sub_agent_state = SubAgentState(
                sub_agent_type="Finder", sub_agent_desc="search files", sub_agent_prompt="find foo"
            )
            sub_session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("find foo")),
                    message.AssistantMessage(parts=message.text_parts_from_str("found it")),
                    TaskMetadataItem(main_agent=TaskMetadata(model_name="test", turn_count=1, task_duration_s=2.0)),
                ]
            )
            await sub_session.wait_for_flush()

            # Main session has only SpawnSubAgentEntry (no ToolResultMessage yet)
            main_session = Session.create(id="spawn-main", work_dir=project_dir)
            main_session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("hello")),
                    message.SpawnSubAgentEntry(
                        session_id=sub_session.id,
                        sub_agent_type="Finder",
                        sub_agent_desc="search files",
                    ),
                ]
            )
            await main_session.wait_for_flush()

            reloaded = Session.load(main_session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())

            sub_events = [e for e in events_list if getattr(e, "session_id", None) == sub_session.id]
            assert sub_events, "Expected sub-agent events from SpawnSubAgentEntry"

            sub_starts = [e for e in sub_events if isinstance(e, events.TaskStartEvent)]
            assert len(sub_starts) == 1
            assert sub_starts[0].sub_agent_state is not None
            assert sub_starts[0].sub_agent_state.sub_agent_type == "Finder"

            # Completed sub-agent should have TaskFinishEvent
            sub_finishes = [e for e in sub_events if isinstance(e, events.TaskFinishEvent)]
            assert len(sub_finishes) == 1

            await close_default_store()

        arun(_test())

    def test_spawn_sub_agent_entry_no_task_finish_when_still_running(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """A sub-agent without TaskMetadataItem is still running; no TaskFinishEvent should be emitted."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            # Sub-agent session is still running (no TaskMetadataItem)
            sub_session = Session.create(id="running-sub", work_dir=project_dir)
            sub_session.sub_agent_state = SubAgentState(
                sub_agent_type="Task", sub_agent_desc="do stuff", sub_agent_prompt="work"
            )
            sub_session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("work")),
                    message.AssistantMessage(parts=message.text_parts_from_str("working...")),
                ]
            )
            await sub_session.wait_for_flush()

            main_session = Session.create(id="running-main", work_dir=project_dir)
            main_session.append_history(
                [
                    message.SpawnSubAgentEntry(
                        session_id=sub_session.id,
                        sub_agent_type="Task",
                        sub_agent_desc="do stuff",
                    ),
                ]
            )
            await main_session.wait_for_flush()

            reloaded = Session.load(main_session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())

            sub_events = [e for e in events_list if getattr(e, "session_id", None) == sub_session.id]
            assert sub_events, "Expected sub-agent events"

            # Should have TaskStartEvent but NOT TaskFinishEvent
            sub_starts = [e for e in sub_events if isinstance(e, events.TaskStartEvent)]
            assert len(sub_starts) == 1

            sub_finishes = [e for e in sub_events if isinstance(e, events.TaskFinishEvent)]
            assert len(sub_finishes) == 0, "Running sub-agent should not emit TaskFinishEvent"

            await close_default_store()

        arun(_test())

    def test_spawn_sub_agent_entry_deduplicates_with_tool_result(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """When both SpawnSubAgentEntry and ToolResultMessage exist, sub-agent events appear only once."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            sub_session = Session.create(id="dedup-sub", work_dir=project_dir)
            sub_session.sub_agent_state = SubAgentState(
                sub_agent_type="Task", sub_agent_desc="test", sub_agent_prompt="test"
            )
            sub_session.append_history(
                [
                    message.AssistantMessage(parts=message.text_parts_from_str("done")),
                    TaskMetadataItem(main_agent=TaskMetadata(model_name="test", turn_count=1, task_duration_s=1.0)),
                ]
            )
            await sub_session.wait_for_flush()

            # Main session has BOTH SpawnSubAgentEntry AND ToolResultMessage
            main_session = Session.create(id="dedup-main", work_dir=project_dir)
            main_session.append_history(
                [
                    message.SpawnSubAgentEntry(
                        session_id=sub_session.id,
                        sub_agent_type="Task",
                        sub_agent_desc="test",
                    ),
                    message.AssistantMessage(
                        parts=[
                            message.ToolCallPart(
                                call_id="agent-call",
                                tool_name="Agent",
                                arguments_json="{}",
                            )
                        ]
                    ),
                    message.ToolResultMessage(
                        call_id="agent-call",
                        tool_name="Agent",
                        output_text="done",
                        status="success",
                        ui_extra=SessionIdUIExtra(session_id=sub_session.id),
                    ),
                ]
            )
            await main_session.wait_for_flush()

            reloaded = Session.load(main_session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())

            # Sub-agent TaskStartEvent should appear exactly once (dedup via seen_sub_agent_sessions)
            sub_starts = [
                e for e in events_list if isinstance(e, events.TaskStartEvent) and e.session_id == sub_session.id
            ]
            assert len(sub_starts) == 1

            await close_default_store()

        arun(_test())

    def test_spawn_sub_agent_entry_codec_roundtrip(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """SpawnSubAgentEntry survives encode/decode via the codec."""
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="codec-test", work_dir=project_dir)
            entry = message.SpawnSubAgentEntry(
                session_id="child-abc",
                sub_agent_type="Finder",
                sub_agent_desc="search stuff",
                fork_context=True,
            )
            session.append_history([entry])
            await session.wait_for_flush()

            loaded = Session.load(session.id, work_dir=project_dir)
            assert len(loaded.conversation_history) == 1
            item = loaded.conversation_history[0]
            assert isinstance(item, message.SpawnSubAgentEntry)
            assert item.session_id == "child-abc"
            assert item.sub_agent_type == "Finder"
            assert item.sub_agent_desc == "search stuff"
            assert item.fork_context is True

            await close_default_store()

        arun(_test())

    def test_replay_interrupt_entry_emits_interrupt_event(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="interrupt-session", work_dir=project_dir)
            session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("hello")),
                    message.InterruptEntry(show_notice=False),
                ]
            )
            await session.wait_for_flush()

            reloaded = Session.load(session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())
            interrupt_event = next(e for e in events_list if isinstance(e, events.InterruptEvent))
            assert interrupt_event.show_notice is False
            await close_default_store()

        arun(_test())

    def test_replay_emits_usage_event_from_assistant_usage(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="usage-session", work_dir=project_dir)
            session.append_history(
                [
                    message.AssistantMessage(
                        response_id="resp-1",
                        parts=message.text_parts_from_str("done"),
                        usage=Usage(
                            input_tokens=30_000,
                            cached_tokens=20_000,
                            output_tokens=12_000,
                            reasoning_tokens=2_000,
                            context_size=46_000,
                            context_limit=300_000,
                            max_tokens=100_000,
                            input_cost=0.001,
                            output_cost=0.002,
                            cache_read_cost=0.0005,
                        ),
                    )
                ]
            )
            await session.wait_for_flush()

            reloaded = Session.load(session.id, work_dir=project_dir)
            events_list = list(reloaded.get_history_item())
            usage_events = [e for e in events_list if isinstance(e, events.UsageEvent)]
            assert len(usage_events) == 1
            usage_event = usage_events[0]
            assert usage_event.session_id == session.id
            assert usage_event.response_id == "resp-1"
            assert usage_event.usage.input_tokens == 30_000
            assert usage_event.usage.cached_tokens == 20_000
            assert usage_event.usage.total_cost is not None
            assert abs(usage_event.usage.total_cost - 0.0035) < 1e-12
            await close_default_store()

        arun(_test())


class TestSessionListAndClean:
    """Tests for Session.list_sessions and clean methods."""

    def test_list_sessions_empty(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "empty_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        sessions = Session.list_sessions(work_dir=project_dir)
        assert sessions == []

    def test_list_sessions_returns_metadata(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir, model_name="gpt-4")
            session.update_title("Session summary")
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test message"))])
            await session.wait_for_flush()

            sessions = Session.list_sessions(work_dir=project_dir)
            assert len(sessions) == 1
            meta = sessions[0]
            assert meta.id == session.id
            assert meta.title == "Session summary"
            assert meta.model_name == "gpt-4"
            assert len(meta.user_messages) == 1
            assert meta.user_messages[0] == "Test message"
            assert meta.messages_count == 1
            await close_default_store()

        arun(_test())

    def test_list_sessions_backfills_user_messages_to_meta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        from klaude_code.session.codec import encode_jsonl_line

        session_id = "backfill_test"
        paths = Session.paths(project_dir)
        session_dir = paths.session_dir(session_id)
        session_dir.mkdir(parents=True, exist_ok=True)

        events_path = paths.events_file(session_id)
        events_path.write_text(
            "".join(
                [
                    encode_jsonl_line(message.UserMessage(parts=message.text_parts_from_str("m1"))),
                    encode_jsonl_line(message.AssistantMessage(parts=message.text_parts_from_str("a1"))),
                    encode_jsonl_line(message.UserMessage(parts=message.text_parts_from_str("m2"))),
                ]
            ),
            encoding="utf-8",
        )

        meta_path = paths.meta_file(session_id)
        meta_path.write_text(
            json.dumps(
                {
                    "id": session_id,
                    "work_dir": str(project_dir),
                    "sub_agent_state": None,
                    "created_at": time.time() - 10,
                    "updated_at": time.time() - 5,
                    "messages_count": 3,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        sessions = Session.list_sessions(work_dir=project_dir)
        assert len(sessions) == 1
        assert sessions[0].id == session_id
        assert sessions[0].user_messages == ["m1", "m2"]

        backfilled = json.loads(meta_path.read_text(encoding="utf-8"))
        assert backfilled["user_messages"] == ["m1", "m2"]


class TestForkSessionCommand:
    def test_fork_session_empty_does_not_create_session(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            from klaude_code.tui.command.fork_session_cmd import ForkSessionCommand

            session = Session(work_dir=project_dir)
            cmd = ForkSessionCommand()
            agent = _ForkSessionDummyAgent(session)
            result = await cmd.run(agent, message.UserInputPayload(text=""))

            assert result.events is not None
            assert len(result.events) == 1
            assert isinstance(result.events[0], events.NoticeEvent)
            assert result.events[0].content == "(no messages to fork)"
            assert Session.list_sessions(work_dir=project_dir) == []
            await close_default_store()

        arun(_test())

    def test_fork_session_copies_history_and_returns_resume_command(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            from klaude_code.tui.command.fork_session_cmd import ForkSessionCommand

            session = Session(work_dir=project_dir, model_name="test-model", model_config_name="test-config")
            session.model_thinking = llm_param.Thinking(type="enabled", budget_tokens=123)
            session.file_tracker["/path/to/file"] = FileStatus(mtime=time.time(), content_sha256="abc")
            session.file_change_summary.record_created("/path/to/created")
            session.file_change_summary.record_edited("/path/to/edited")
            session.file_change_summary.add_diff(added=4, removed=1)
            session.todos.append(TodoItem(content="t1", status="pending"))
            session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("Hello")),
                    message.AssistantMessage(parts=message.text_parts_from_str("Hi")),
                ]
            )
            await session.wait_for_flush()

            cmd = ForkSessionCommand()
            agent = _ForkSessionDummyAgent(session)
            result = await cmd.run(agent, message.UserInputPayload(text=""))

            assert result.operations is not None
            assert len(result.operations) == 1
            fork_op = result.operations[0]
            assert isinstance(fork_op, op.ForkAndSwitchSessionOperation)
            assert fork_op.session_id == session.id
            new_id = fork_op.new_session_id
            assert new_id
            assert new_id != session.id
            assert fork_op.original_session_short_id

            assert Session.exists(new_id, work_dir=project_dir)
            forked = Session.load(new_id, work_dir=project_dir)
            assert forked.work_dir == session.work_dir
            assert forked.model_name == session.model_name
            assert forked.model_config_name == session.model_config_name
            assert forked.model_thinking == session.model_thinking
            assert forked.file_tracker.keys() == session.file_tracker.keys()
            assert forked.file_change_summary == session.file_change_summary
            assert len(forked.todos) == len(session.todos)
            assert len(forked.conversation_history) == len(session.conversation_history)
            assert isinstance(forked.conversation_history[0], message.UserMessage)
            assert isinstance(forked.conversation_history[1], message.AssistantMessage)
            assert message.join_text_parts(forked.conversation_history[0].parts) == "Hello"
            assert message.join_text_parts(forked.conversation_history[1].parts) == "Hi"

            await close_default_store()

        arun(_test())

    def test_list_sessions_sorted_by_updated_at(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session1 = Session(work_dir=project_dir)
            session1.created_at = time.time() - 100
            session1.append_history([message.UserMessage(parts=message.text_parts_from_str("First"))])
            await session1.wait_for_flush()

            session2 = Session(work_dir=project_dir)
            session2.created_at = time.time()
            session2.append_history([message.UserMessage(parts=message.text_parts_from_str("Second"))])
            await session2.wait_for_flush()

            sessions = Session.list_sessions(work_dir=project_dir)
            assert len(sessions) == 2
            assert sessions[0].id == session2.id
            assert sessions[1].id == session1.id
            await close_default_store()

        arun(_test())

    def test_most_recent_session_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        # No sessions yet
        assert Session.most_recent_session_id(work_dir=project_dir) is None

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
            await session.wait_for_flush()
            assert Session.most_recent_session_id(work_dir=project_dir) == session.id
            await close_default_store()

        arun(_test())

    def test_most_recent_session_id_skips_archived(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            archived_session = Session(work_dir=project_dir, archived=True)
            archived_session.append_history([message.UserMessage(parts=message.text_parts_from_str("old"))])
            await archived_session.wait_for_flush()

            visible_session = Session(work_dir=project_dir)
            visible_session.append_history([message.UserMessage(parts=message.text_parts_from_str("new"))])
            await visible_session.wait_for_flush()

            assert Session.most_recent_session_id(work_dir=project_dir) == visible_session.id
            await close_default_store()

        arun(_test())


class TestStripDanglingToolCalls:
    """Tests for Session._strip_dangling_tool_calls."""

    def test_no_dangling_calls_unchanged(self):
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AssistantMessage(
                parts=[
                    message.TextPart(text="calling tool"),
                    message.ToolCallPart(call_id="c1", tool_name="Bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(call_id="c1", tool_name="Bash", status="success", output_text="ok"),
        ]
        result = Session._strip_dangling_tool_calls(items)
        assert len(result) == 3
        assert isinstance(result[1], message.AssistantMessage)
        tool_calls = [p for p in result[1].parts if isinstance(p, message.ToolCallPart)]
        assert len(tool_calls) == 1

    def test_trailing_assistant_with_only_dangling_calls_gets_synthetic_result(self):
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="c1", tool_name="Agent", arguments_json="{}"),
                ]
            ),
        ]
        result = Session._strip_dangling_tool_calls(items)
        # AssistantMessage kept, synthetic ToolResultMessage appended
        assert len(result) == 3
        assert isinstance(result[0], message.UserMessage)
        assert isinstance(result[1], message.AssistantMessage)
        assert isinstance(result[2], message.ToolResultMessage)
        assert result[2].call_id == "c1"
        assert result[2].status == "error"
        assert "interrupted" in result[2].output_text

    def test_trailing_assistant_keeps_text_patches_dangling_calls(self):
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.AssistantMessage(
                parts=[
                    message.TextPart(text="Let me explore"),
                    message.ToolCallPart(call_id="c1", tool_name="Agent", arguments_json="{}"),
                    message.ToolCallPart(call_id="c2", tool_name="Bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(call_id="c2", tool_name="Bash", status="success", output_text="ok"),
        ]
        result = Session._strip_dangling_tool_calls(items)
        # AssistantMessage preserved intact; synthetic result for c1 inserted after it
        assert len(result) == 4
        assistant = result[1]
        assert isinstance(assistant, message.AssistantMessage)
        assert len(assistant.parts) == 3  # all parts preserved
        # Synthetic result for dangling c1
        synthetic = result[2]
        assert isinstance(synthetic, message.ToolResultMessage)
        assert synthetic.call_id == "c1"
        assert synthetic.status == "error"
        # Existing result for c2
        assert isinstance(result[3], message.ToolResultMessage)
        assert result[3].call_id == "c2"

    def test_concurrent_tools_partial_completion(self):
        """Simulate fork_context scenario: AssistantMessage with 4 tool calls,
        only some have results (concurrent tools where some finished first)."""
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("analyze repo")),
            message.AssistantMessage(
                parts=[
                    message.TextPart(text="I'll analyze the repo"),
                    message.ToolCallPart(call_id="agent1", tool_name="Agent", arguments_json='{"fork_context":true}'),
                    message.ToolCallPart(call_id="agent2", tool_name="Agent", arguments_json='{"fork_context":true}'),
                    message.ToolCallPart(call_id="bash1", tool_name="Bash", arguments_json='{"command":"ls"}'),
                ]
            ),
            message.ToolResultMessage(call_id="bash1", tool_name="Bash", status="success", output_text="file1\nfile2"),
        ]
        result = Session._strip_dangling_tool_calls(items)
        # AssistantMessage preserved; synthetic results for agent1 and agent2 added
        assert len(result) == 5  # user + assistant + synthetic(agent1) + synthetic(agent2) + real(bash1)
        assistant = result[1]
        assert isinstance(assistant, message.AssistantMessage)
        # All parts preserved (text + 3 tool calls)
        assert len(assistant.parts) == 4
        # Synthetic results for dangling calls
        assert isinstance(result[2], message.ToolResultMessage)
        assert result[2].call_id == "agent1"
        assert result[2].status == "error"
        assert isinstance(result[3], message.ToolResultMessage)
        assert result[3].call_id == "agent2"
        assert result[3].status == "error"
        # Real result
        assert isinstance(result[4], message.ToolResultMessage)
        assert result[4].call_id == "bash1"
        assert result[4].status == "success"

    def test_empty_history(self):
        result = Session._strip_dangling_tool_calls([])
        assert result == []

    def test_non_assistant_messages_pass_through(self):
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("hi")),
            message.DeveloperMessage(parts=[message.TextPart(text="system info")]),
        ]
        result = Session._strip_dangling_tool_calls(items)
        assert len(result) == 2

    def test_thinking_parts_preserved_with_synthetic_result(self):
        items: list[message.HistoryEvent] = [
            message.UserMessage(parts=message.text_parts_from_str("think")),
            message.AssistantMessage(
                parts=[
                    message.ThinkingTextPart(text="Let me think about this..."),
                    message.TextPart(text="Here's my plan"),
                    message.ToolCallPart(call_id="c1", tool_name="Agent", arguments_json="{}"),
                ]
            ),
        ]
        result = Session._strip_dangling_tool_calls(items)
        assert len(result) == 3
        assistant = result[1]
        assert isinstance(assistant, message.AssistantMessage)
        # All parts preserved including the dangling tool call
        assert len(assistant.parts) == 3
        assert isinstance(assistant.parts[0], message.ThinkingTextPart)
        assert isinstance(assistant.parts[1], message.TextPart)
        assert isinstance(assistant.parts[2], message.ToolCallPart)
        # Synthetic result appended
        synthetic = result[2]
        assert isinstance(synthetic, message.ToolResultMessage)
        assert synthetic.call_id == "c1"
        assert synthetic.status == "error"


class TestGetLlmHistoryDanglingToolCalls:
    """Integration tests: get_llm_history strips dangling tool calls."""

    def test_get_llm_history_patches_trailing_dangling_calls(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            message.UserMessage(parts=message.text_parts_from_str("hello")),
            message.AssistantMessage(
                parts=[
                    message.TextPart(text="I'll run some tools"),
                    message.ToolCallPart(call_id="c1", tool_name="Agent", arguments_json="{}"),
                    message.ToolCallPart(call_id="c2", tool_name="Bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(call_id="c2", tool_name="Bash", status="success", output_text="ok"),
        ]
        result = session.get_llm_history()
        # AssistantMessage preserved; synthetic result for c1 inserted
        assert len(result) == 4
        assistant = result[1]
        assert isinstance(assistant, message.AssistantMessage)
        tool_calls = [p for p in assistant.parts if isinstance(p, message.ToolCallPart)]
        assert len(tool_calls) == 2  # both preserved
        # Synthetic result for dangling c1
        assert isinstance(result[2], message.ToolResultMessage)
        assert result[2].call_id == "c1"
        assert result[2].status == "error"
        # Real result for c2
        assert isinstance(result[3], message.ToolResultMessage)
        assert result[3].call_id == "c2"

    def test_get_llm_history_no_dangling_no_change(self, tmp_path: Path):
        session = Session(work_dir=tmp_path)
        session.conversation_history = [
            message.UserMessage(parts=message.text_parts_from_str("hello")),
            message.AssistantMessage(
                parts=[
                    message.ToolCallPart(call_id="c1", tool_name="Bash", arguments_json="{}"),
                ]
            ),
            message.ToolResultMessage(call_id="c1", tool_name="Bash", status="success", output_text="ok"),
        ]
        result = session.get_llm_history()
        assert len(result) == 3
        assistant = result[1]
        assert isinstance(assistant, message.AssistantMessage)
        assert len([p for p in assistant.parts if isinstance(p, message.ToolCallPart)]) == 1


class TestSessionMetaBrief:
    """Tests for Session.SessionMetaBrief"""

    def test_create_meta_brief(self):
        meta = Session.SessionMetaBrief(
            id="test123",
            created_at=1700000000.0,
            updated_at=1700001000.0,
            work_dir="/home/user/project",
            path="/home/user/.klaude/projects/test/sessions/test123.json",
            title="Session title",
            user_messages=["Hello world"],
            messages_count=5,
            model_name="gpt-4",
            archived=True,
        )
        assert meta.id == "test123"
        assert meta.created_at == 1700000000.0
        assert meta.updated_at == 1700001000.0
        assert meta.work_dir == "/home/user/project"
        assert meta.path == "/home/user/.klaude/projects/test/sessions/test123.json"
        assert meta.title == "Session title"
        assert meta.user_messages == ["Hello world"]
        assert meta.messages_count == 5
        assert meta.model_name == "gpt-4"
        assert meta.archived is True

    def test_default_values(self):
        meta = Session.SessionMetaBrief(
            id="test",
            created_at=0.0,
            updated_at=0.0,
            work_dir="",
            path="",
        )
        assert meta.title is None
        assert meta.user_messages == []
        assert meta.messages_count == -1
        assert meta.model_name is None
        assert meta.session_state is None
        assert meta.archived is False


class TestSessionTitle:
    def test_update_title_persists_to_meta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
            await session.wait_for_flush()

            assert session.update_title("New title") is True
            assert session.update_title("New title") is False

            loaded = Session.load_meta(session.id, work_dir=project_dir)
            assert loaded.title == "New title"
            await close_default_store()

        arun(_test())


class TestSessionExists:
    def test_returns_false_when_missing(self, tmp_path: Path):
        assert Session.exists("does-not-exist", work_dir=tmp_path) is False

    def test_returns_true_when_persisted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
            await session.wait_for_flush()

            assert Session.exists(session.id, work_dir=project_dir) is True
            await close_default_store()

        arun(_test())


class TestCliResume:
    def test_errors_when_session_missing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        import klaude_code.cli.main as _cli_main
        from klaude_code.cli.main import app

        _orig_run = _cli_main.asyncio.run

        def _should_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("interactive runtime should not start when --resume <id> is invalid")

        _cli_main.asyncio.run = _should_not_run  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        try:
            runner = CliRunner()
            result = runner.invoke(app, ["--resume", "missing-session-id"])
            assert result.exit_code == 2
            assert "not found" in result.output
        finally:
            _cli_main.asyncio.run = _orig_run  # type: ignore[assignment]

    def test_errors_on_conflicting_flags(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        import klaude_code.cli.main as _cli_main
        from klaude_code.cli.main import app

        _orig_run = _cli_main.asyncio.run

        def _should_not_run(*_args: object, **_kwargs: object) -> None:
            raise AssertionError("interactive runtime should not start when flags conflict")

        _cli_main.asyncio.run = _should_not_run  # type: ignore[assignment]  # ty: ignore[invalid-assignment]
        try:
            runner = CliRunner()
            result = runner.invoke(app, ["--resume", "any", "--continue"])
            assert result.exit_code == 2
            assert "cannot be combined" in result.output
        finally:
            _cli_main.asyncio.run = _orig_run  # type: ignore[assignment]


class TestFindSessionsByPrefix:
    """Tests for Session.find_sessions_by_prefix method."""

    def test_find_by_prefix_single_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="abcd1234", work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await session.wait_for_flush()

            matches = Session.find_sessions_by_prefix("abc", work_dir=project_dir)
            assert matches == ["abcd1234"]
            await close_default_store()

        arun(_test())

    def test_find_by_prefix_multiple_matches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            s1 = Session.create(id="abc123", work_dir=project_dir)
            s1.append_history([message.UserMessage(parts=message.text_parts_from_str("Test 1"))])
            await s1.wait_for_flush()

            s2 = Session.create(id="abc456", work_dir=project_dir)
            s2.append_history([message.UserMessage(parts=message.text_parts_from_str("Test 2"))])
            await s2.wait_for_flush()

            matches = Session.find_sessions_by_prefix("abc", work_dir=project_dir)
            assert sorted(matches) == ["abc123", "abc456"]
            await close_default_store()

        arun(_test())

    def test_find_by_prefix_no_match(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="xyz789", work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await session.wait_for_flush()

            matches = Session.find_sessions_by_prefix("abc", work_dir=project_dir)
            assert matches == []
            await close_default_store()

        arun(_test())

    def test_find_by_prefix_excludes_sub_agents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            main_session = Session.create(id="abc_main", work_dir=project_dir)
            main_session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await main_session.wait_for_flush()

            sub_session = Session.create(id="abc_sub", work_dir=project_dir)
            sub_session.sub_agent_state = SubAgentState(
                sub_agent_type="Task", sub_agent_desc="test", sub_agent_prompt="test"
            )
            sub_session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("Done"))])
            await sub_session.wait_for_flush()

            matches = Session.find_sessions_by_prefix("abc", work_dir=project_dir)
            assert matches == ["abc_main"]
            await close_default_store()

        arun(_test())

    def test_find_by_prefix_case_insensitive(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="AbCd1234", work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await session.wait_for_flush()

            matches = Session.find_sessions_by_prefix("ABCD", work_dir=project_dir)
            assert matches == ["AbCd1234"]
            await close_default_store()

        arun(_test())


class TestShortestUniquePrefix:
    """Tests for Session.shortest_unique_prefix method."""

    def test_single_session_returns_min_length(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="abcdef123456", work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await session.wait_for_flush()

            prefix = Session.shortest_unique_prefix("abcdef123456", work_dir=project_dir)
            assert prefix == "abcd"  # min_length is 4
            await close_default_store()

        arun(_test())

    def test_needs_longer_prefix_to_disambiguate(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            s1 = Session.create(id="abcd1111", work_dir=project_dir)
            s1.append_history([message.UserMessage(parts=message.text_parts_from_str("Test 1"))])
            await s1.wait_for_flush()

            s2 = Session.create(id="abcd2222", work_dir=project_dir)
            s2.append_history([message.UserMessage(parts=message.text_parts_from_str("Test 2"))])
            await s2.wait_for_flush()

            prefix1 = Session.shortest_unique_prefix("abcd1111", work_dir=project_dir)
            prefix2 = Session.shortest_unique_prefix("abcd2222", work_dir=project_dir)
            assert prefix1 == "abcd1"
            assert prefix2 == "abcd2"
            await close_default_store()

        arun(_test())

    def test_excludes_sub_agents(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        project_dir = tmp_path / "test_project"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            main = Session.create(id="abcd1111", work_dir=project_dir)
            main.append_history([message.UserMessage(parts=message.text_parts_from_str("Test"))])
            await main.wait_for_flush()

            sub = Session.create(id="abcd2222", work_dir=project_dir)
            sub.sub_agent_state = SubAgentState(sub_agent_type="Task", sub_agent_desc="test", sub_agent_prompt="test")
            sub.append_history([message.AssistantMessage(parts=message.text_parts_from_str("Done"))])
            await sub.wait_for_flush()

            # Sub-agent should not affect the prefix calculation for main session
            prefix = Session.shortest_unique_prefix("abcd1111", work_dir=project_dir)
            assert prefix == "abcd"  # min_length, since abcd2222 is a sub-agent
            await close_default_store()

        arun(_test())
