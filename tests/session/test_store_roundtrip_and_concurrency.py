# pyright: reportPrivateUsage=false
"""Characterization tests for session persistence + store concurrency (group G5).

These lock in the CURRENT observable behavior of:
  - Session save -> load round-trip (history + meta fidelity).
  - JsonlSessionStore.update_meta read-merge-write semantics.
  - Concurrent meta updates / history appends under the store's threading.Lock.

They assert what the code currently DOES, not what it ideally should do.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import events, llm_param, message
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SubAgentState,
    TaskMetadataItem,
    TodoItem,
)
from klaude_code.session.session import Session
from klaude_code.session.store import (
    JsonlSessionStore,
    build_meta_snapshot,
    count_file_lines,
    register_session_history_observer,
)
from klaude_code.session.store_registry import close_default_store, get_store_for_path


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def test_find_user_message_copies_only_hit_and_reserves_retracted_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        first = message.UserMessage(id="first", parts=message.text_parts_from_str("first"))
        target = message.UserMessage(id="target", parts=message.text_parts_from_str("target"))
        session.append_history([first, target, message.RetractEntry(retracted_text="target", retracted_line=1)])
        await session.wait_for_flush()
        store = get_store_for_path(tmp_path)
        copied: list[str | None] = []
        original = message.UserMessage.model_copy

        def copy(item: message.UserMessage, **kwargs: Any) -> message.UserMessage:
            copied.append(item.id)
            return original(item, **kwargs)

        monkeypatch.setattr(message.UserMessage, "model_copy", copy)
        found = store.find_user_message(session.id, "target")
        assert found == target
        assert found is not None
        found.parts.clear()
        assert store.find_user_message(session.id, "target") == target
        assert store.find_user_message(session.id, "absent") is None
        assert copied == ["target", "target"]

    arun(_test())


@pytest.fixture(autouse=True)
def _isolate_home(isolated_home: Path) -> Path:
    return isolated_home


# =====================================================================
# 1. Session save -> load round-trip: full fidelity of history + meta.
# =====================================================================


class TestSaveLoadRoundTrip:
    def test_full_roundtrip_history_and_meta(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(
                work_dir=project_dir,
                title="Round trip",
                model_name="model-x",
                model_config_name="config-x",
                model_thinking=llm_param.Thinking(reasoning_effort="medium"),
                prompt_cache_key="shared-cache-lineage",
                archived=False,
            )
            session.todos = [
                TodoItem(content="alpha", status="completed"),
                TodoItem(content="beta", status="pending"),
            ]
            session.file_tracker = {
                "/a.py": FileStatus(mtime=111.0, content_sha256="aaa"),
                "/b.py": FileStatus(mtime=222.0, content_sha256="bbb"),
            }
            session.file_change_summary = FileChangeSummary(
                created_files=["/a.py"],
                edited_files=["/b.py"],
                deleted_files=[],
                diff_lines_added=7,
                diff_lines_removed=3,
            )
            history: list[message.HistoryEvent] = [
                message.UserMessage(parts=message.text_parts_from_str("first user")),
                message.AssistantMessage(parts=message.text_parts_from_str("first assistant")),
                message.UserMessage(parts=message.text_parts_from_str("second user")),
                message.AssistantMessage(
                    parts=[
                        message.TextPart(text="calling"),
                        message.ToolCallPart(call_id="c1", tool_name="Bash", arguments_json='{"command":"ls"}'),
                    ]
                ),
                message.ToolResultMessage(call_id="c1", tool_name="Bash", status="success", output_text="ok"),
            ]
            session.append_history(history)
            await session.wait_for_flush()

            loaded = Session.load(session.id, work_dir=project_dir)

            # Meta fields preserved.
            assert loaded.id == session.id
            assert loaded.title == "Round trip"
            assert loaded.model_name == "model-x"
            assert loaded.model_config_name == "config-x"
            assert loaded.model_thinking is not None
            assert loaded.model_thinking.reasoning_effort == "medium"
            assert loaded.model_effort is None
            assert loaded.prompt_cache_key == "shared-cache-lineage"
            assert loaded.archived is False
            assert [t.content for t in loaded.todos] == ["alpha", "beta"]
            assert [t.status for t in loaded.todos] == ["completed", "pending"]
            assert set(loaded.file_tracker.keys()) == {"/a.py", "/b.py"}
            assert loaded.file_tracker["/a.py"].content_sha256 == "aaa"
            assert loaded.file_change_summary.created_files == ["/a.py"]
            assert loaded.file_change_summary.edited_files == ["/b.py"]
            assert loaded.file_change_summary.diff_lines_added == 7
            assert loaded.file_change_summary.diff_lines_removed == 3

            # History preserved with full fidelity (order + types + content).
            assert len(loaded.conversation_history) == len(history)
            assert isinstance(loaded.conversation_history[0], message.UserMessage)
            assert message.join_text_parts(loaded.conversation_history[0].parts) == "first user"
            assert isinstance(loaded.conversation_history[1], message.AssistantMessage)
            assert message.join_text_parts(loaded.conversation_history[1].parts) == "first assistant"
            assistant_with_tool = loaded.conversation_history[3]
            assert isinstance(assistant_with_tool, message.AssistantMessage)
            tool_calls = [p for p in assistant_with_tool.parts if isinstance(p, message.ToolCallPart)]
            assert len(tool_calls) == 1
            assert tool_calls[0].call_id == "c1"
            assert tool_calls[0].arguments_json == '{"command":"ls"}'
            result = loaded.conversation_history[4]
            assert isinstance(result, message.ToolResultMessage)
            assert result.call_id == "c1"
            assert result.output_text == "ok"

            # messages_count counts user + assistant + tool result entries.
            assert loaded.messages_count == 5

            await close_default_store()

        arun(_test())

    def test_load_meta_omits_history_while_persisted_meta_keeps_user_messages(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir, model_name="m")
            session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("u1")),
                    message.AssistantMessage(parts=message.text_parts_from_str("a1")),
                    message.UserMessage(parts=message.text_parts_from_str("u2")),
                ]
            )
            await session.wait_for_flush()

            meta = Session.load_meta(session.id, work_dir=project_dir)
            # load_meta does NOT rebuild conversation_history.
            assert meta.conversation_history == []
            # Session.user_messages is computed from conversation_history, which
            # is empty after load_meta, so the property returns [] even though
            # the user-message cache is persisted in meta.json (see below).
            assert meta.user_messages == []
            # The persisted meta.json DOES carry the cached user_messages list.
            raw = json.loads(Session.paths(project_dir).meta_file(session.id).read_text(encoding="utf-8"))
            assert raw["user_messages"] == ["u1", "u2"]
            await close_default_store()

        arun(_test())


# =====================================================================
# 2. store.update_meta merge-update behavior.
# =====================================================================


@pytest.mark.parametrize("assistant_count", [1, 2])
def test_partial_metadata_retry_calibrates_assistant_lines_and_compaction_replay(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, assistant_count: int
) -> None:
    import klaude_code.session.store as store_module

    async def test() -> None:
        session = Session(work_dir=tmp_path)
        metadata = [TaskMetadataItem(background_task_id=f"task-{index}") for index in range(2)]
        original_encode = store_module.encode_jsonl_line
        failed = False

        def encode(item: message.HistoryEvent) -> str:
            nonlocal failed
            if item is metadata[1] and not failed:
                failed = True
                raise OSError("exact partial write")
            return original_encode(item)

        monkeypatch.setattr(store_module, "encode_jsonl_line", encode)
        session.append_history(metadata, deduplicate_background_tasks=True)
        with pytest.raises(OSError, match="exact partial write"):
            await session.wait_for_background_task_flush()
        path = Session.paths(tmp_path).events_file(session.id)
        assert path.read_text() == original_encode(metadata[0])

        assistant = message.AssistantMessage(parts=message.text_parts_from_str("must retain A"))
        assistants = [assistant.model_copy(deep=True) for _ in range(assistant_count)]
        session.append_history(assistants)
        await session.wait_for_flush()
        session.append_history(metadata, deduplicate_background_tasks=True)
        await session.wait_for_background_task_flush()
        assert session.conversation_history == [*metadata, *assistants]
        assert [session.line_index_of(i) for i in range(len(session.conversation_history))] == [
            0,
            assistant_count + 1,
            *range(1, assistant_count + 1),
        ]
        rows = session._store.load_history_lines(session.id)
        for index, item in enumerate(session.conversation_history):
            assert rows[session.line_index_of(index)][1] == item
        assert session.line_index_of(len(session.conversation_history)) == len(rows)

        session.append_history(
            [message.CompactionEntry(summary="summary", first_kept_index=2, first_kept_line=session.line_index_of(2))]
        )
        await session.wait_for_flush()
        loaded = Session.load(session.id, work_dir=tmp_path)
        for current in (session, loaded):
            kept = [item for item in current.get_llm_history() if isinstance(item, message.AssistantMessage)]
            assert kept == assistants
        replayed = [
            event.content for event in loaded.get_history_item() if isinstance(event, events.AssistantTextDeltaEvent)
        ]
        assert replayed == ["must retain A"] * assistant_count
        assert [loaded.line_index_of(i) for i in range(len(loaded.conversation_history))] == list(range(len(rows) + 1))

    arun(test())


@pytest.mark.parametrize("background_first", [False, True])
@pytest.mark.parametrize("assistant_between", [False, True])
@pytest.mark.parametrize("wait_order", ["user", "background", "concurrent"])
def test_overlapping_flush_receipts_preserve_physical_lines_and_compaction(
    tmp_path: Path, background_first: bool, assistant_between: bool, wait_order: str
) -> None:
    from klaude_code.session.codec import encode_jsonl_line

    async def test() -> None:
        session = Session(work_dir=tmp_path)
        user = message.UserMessage(id="user", parts=message.text_parts_from_str("original input"))
        path = Session.paths(tmp_path).events_file(session.id)
        path.parent.mkdir(parents=True)
        path.write_text(encode_jsonl_line(user) + '{"type":')
        session = Session.load(session.id, work_dir=tmp_path)
        metadata = TaskMetadataItem(background_task_id="task")
        assistant = message.AssistantMessage(parts=message.text_parts_from_str("must retain A"))

        def append_user() -> None:
            session.append_history([user], deduplicate_user_inputs=True)

        def append_background() -> None:
            session.append_history([metadata], deduplicate_background_tasks=True)

        first, second = (append_background, append_user) if background_first else (append_user, append_background)
        first()
        if assistant_between:
            session.append_history([assistant])
        second()
        if wait_order == "concurrent":
            await asyncio.gather(session.wait_for_flush(), session.wait_for_background_task_flush())
        elif wait_order == "background":
            await session.wait_for_background_task_flush()
            await session.wait_for_flush()
        else:
            await session.wait_for_flush()
            await session.wait_for_background_task_flush()

        session.append_history([assistant])
        await session.wait_for_flush()
        rows = session._store.load_history_lines(session.id)
        assert session.line_index_of(len(session.conversation_history)) == len(rows)
        for index, item in enumerate(session.conversation_history):
            assert rows[session.line_index_of(index)][1] == item

        kept_index = len(session.conversation_history) - 1
        assert session.line_index_of(kept_index) == len(rows) - 1
        session.append_history(
            [
                message.CompactionEntry(
                    summary="summary", first_kept_index=kept_index, first_kept_line=session.line_index_of(kept_index)
                )
            ]
        )
        await session.wait_for_flush()
        loaded = Session.load(session.id, work_dir=tmp_path)
        for current in (session, loaded):
            assert [item for item in current.get_llm_history() if isinstance(item, message.AssistantMessage)] == [
                assistant
            ]
        assert [
            event.content for event in loaded.get_history_item() if isinstance(event, events.AssistantTextDeltaEvent)
        ] == ["must retain A"]

    arun(test())


@pytest.mark.parametrize("append_while_waiting", [False, True])
def test_flush_receipts_calibrate_new_pending_batches_during_overlapping_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, append_while_waiting: bool
) -> None:
    import klaude_code.session.store as store_module

    async def test() -> None:
        session = Session(work_dir=tmp_path)
        user = message.UserMessage(id="user", parts=message.text_parts_from_str("original input"))
        path = Session.paths(tmp_path).events_file(session.id)
        path.parent.mkdir(parents=True)
        path.write_text(store_module.encode_jsonl_line(user) + '{"type":')
        session = Session.load(session.id, work_dir=tmp_path)
        metadata = TaskMetadataItem(background_task_id="first-task")
        entered = threading.Event()
        release = threading.Event()
        original_encode = store_module.encode_jsonl_line

        def encode(item: message.HistoryEvent) -> str:
            if item is metadata:
                entered.set()
                assert release.wait(timeout=5)
            return original_encode(item)

        monkeypatch.setattr(store_module, "encode_jsonl_line", encode)
        session.append_history([user], deduplicate_user_inputs=True)
        session.append_history([metadata], deduplicate_background_tasks=True)
        waiting = asyncio.create_task(session.wait_for_background_task_flush())
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert not waiting.done()
            if not append_while_waiting:
                release.set()
                await asyncio.wait_for(waiting, timeout=5)
            session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("between batches"))])
            session.append_history(
                [message.UserMessage(id="next-user", parts=message.text_parts_from_str("next input"))],
                deduplicate_user_inputs=True,
            )
            session.append_history(
                [TaskMetadataItem(background_task_id="next-task")], deduplicate_background_tasks=True
            )
        finally:
            release.set()
        await asyncio.wait_for(
            asyncio.gather(waiting, session.wait_for_background_task_flush(), session.wait_for_flush()), timeout=5
        )
        rows = session._store.load_history_lines(session.id)
        assert session.line_index_of(len(session.conversation_history)) == len(rows) == 5
        for index, item in enumerate(session.conversation_history):
            assert rows[session.line_index_of(index)][1] == item
        session.append_history(
            [message.RetractEntry(retracted_text="next input", retracted_line=session.line_index_of(3))]
        )
        await session.wait_for_flush()
        loaded = Session.load(session.id, work_dir=tmp_path)
        assert [item.id for item in loaded.conversation_history if isinstance(item, message.UserMessage)] == ["user"]
        assert any(isinstance(item, message.AssistantMessage) for item in loaded.conversation_history)

    arun(test())


def _make_store(work_dir: Path) -> JsonlSessionStore:
    # get_store_for_path caches per project key; close_default_store cleans up.
    return get_store_for_path(work_dir)


def _seed_meta(store: JsonlSessionStore, session_id: str, work_dir: Path, **overrides: Any) -> dict[str, Any]:
    meta = build_meta_snapshot(
        session_id=session_id,
        work_dir=work_dir,
        title=overrides.get("title", "seed title"),
        file_tracker={},
        file_change_summary=FileChangeSummary(),
        todos=[],
        user_messages=overrides.get("user_messages", ["hi"]),
        created_at=1000.0,
        updated_at=1000.0,
        messages_count=overrides.get("messages_count", 1),
        model_name=overrides.get("model_name", "seed-model"),
        archived=overrides.get("archived", False),
        model_config_name=overrides.get("model_config_name", "seed-config"),
        model_thinking=None,
    )
    created = store.create_meta_if_missing(session_id, meta)
    assert created is True
    return meta


class TestUpdateMetaMerge:
    def test_update_merges_field_preserving_others(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "sess-merge"
        _seed_meta(store, sid, project_dir)

        assert store.update_meta(sid, {"title": "updated title"}) is True

        raw = store.load_meta(sid)
        assert raw is not None
        # Updated field changed.
        assert raw["title"] == "updated title"
        # Other fields preserved.
        assert raw["model_name"] == "seed-model"
        assert raw["model_config_name"] == "seed-config"
        assert raw["messages_count"] == 1
        assert raw["user_messages"] == ["hi"]
        assert raw["id"] == sid

    def test_update_returns_false_when_meta_missing(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        # No meta file created yet.
        assert store.update_meta("does-not-exist", {"title": "x"}) is False

    def test_update_with_none_value_drops_key(self, tmp_path: Path) -> None:
        # update_meta strips None-valued keys from the persisted dict.
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "sess-none"
        _seed_meta(store, sid, project_dir, title="has title")

        assert store.update_meta(sid, {"title": None}) is True
        raw = store.load_meta(sid)
        assert raw is not None
        assert "title" not in raw
        # Sibling field still present.
        assert raw["model_name"] == "seed-model"

    def test_create_meta_if_missing_does_not_overwrite(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "sess-create"
        _seed_meta(store, sid, project_dir, title="original")

        # Second create attempt with a different title returns False and keeps original.
        second = build_meta_snapshot(
            session_id=sid,
            work_dir=project_dir,
            title="replacement",
            file_tracker={},
            file_change_summary=FileChangeSummary(),
            todos=[],
            user_messages=[],
            created_at=2000.0,
            updated_at=2000.0,
            messages_count=9,
            model_name=None,
            archived=False,
            model_config_name=None,
            model_thinking=None,
        )
        assert store.create_meta_if_missing(sid, second) is False
        raw = store.load_meta(sid)
        assert raw is not None
        assert raw["title"] == "original"


# =====================================================================
# 3. Concurrency: distinct meta fields / history appends, no lost updates.
# =====================================================================


class TestConcurrentMetaUpdates:
    def test_threads_updating_distinct_fields_no_lost_updates(self, tmp_path: Path) -> None:
        """Multiple threads each update a DISTINCT meta field.

        The store serializes update_meta via threading.Lock (read-merge-write),
        so concurrent updates to different keys currently must all survive.
        This locks in the no-lost-update behavior for the in-process store.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "sess-concurrent"
        _seed_meta(store, sid, project_dir)

        # Each thread writes a unique key so the merge must accumulate all of them.
        n = 32
        keys = [f"field_{i}" for i in range(n)]
        start = threading.Barrier(n)
        errors: list[Exception] = []

        def _worker(key: str) -> None:
            try:
                start.wait()
                assert store.update_meta(sid, {key: key}) is True
            except Exception as exc:  # pragma: no cover - surfaced via errors list
                errors.append(exc)

        threads = [threading.Thread(target=_worker, args=(k,)) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        raw = store.load_meta(sid)
        assert raw is not None
        # No lost updates: every distinct field landed.
        missing = [k for k in keys if raw.get(k) != k]
        assert missing == [], f"lost updates for keys: {missing}"
        # Pre-existing seed fields preserved.
        assert raw["model_name"] == "seed-model"
        assert raw["id"] == sid

    def test_threads_incrementing_same_field_via_read_modify_write(self, tmp_path: Path) -> None:
        """Read-modify-write of the SAME field from app code (read meta, compute,
        write back) is NOT atomic across the read boundary.

        update_meta itself is atomic, but a caller that does
        load_meta() -> mutate -> update_meta() has a classic TOCTOU window.
        This test characterizes the CURRENT outcome of that pattern.

        NOTE: This pattern can lose updates because each thread reads the counter
        before others write. We assert the observed final value is in the valid
        range [1, n] rather than asserting the ideal n, documenting that the
        per-key update_meta lock does NOT protect a caller-side read-modify-write.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "sess-counter"
        _seed_meta(store, sid, project_dir)
        store.update_meta(sid, {"counter": 0})

        n = 16
        start = threading.Barrier(n)

        def _worker() -> None:
            start.wait()
            raw = store.load_meta(sid)
            assert raw is not None
            current = int(raw.get("counter", 0))
            store.update_meta(sid, {"counter": current + 1})

        threads = [threading.Thread(target=_worker) for _ in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        raw = store.load_meta(sid)
        assert raw is not None
        final = int(raw["counter"])
        # Characterization: final is a valid increment count but may be < n
        # due to the caller-side TOCTOU (load_meta/update_meta are separate ops).
        assert 1 <= final <= n

    def test_concurrent_history_appends_all_persisted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Many append_history calls on one session all land in events.jsonl.

        append_history goes through the async writer queue (single-threaded
        consumer), so all appended items must be persisted and re-loadable.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            total = 50
            for i in range(total):
                session.append_history([message.UserMessage(parts=message.text_parts_from_str(f"msg-{i}"))])
            await session.wait_for_flush()

            loaded = Session.load(session.id, work_dir=project_dir)
            texts = [
                message.join_text_parts(it.parts)
                for it in loaded.conversation_history
                if isinstance(it, message.UserMessage)
            ]
            assert texts == [f"msg-{i}" for i in range(total)]
            await close_default_store()

        arun(_test())


# =====================================================================
# Sub-agent meta: identity keys persist, display state does not.
# =====================================================================


class TestSubAgentMetaRoundTrip:
    def test_sub_agent_identity_persists_without_sub_agent_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="sub-1", work_dir=project_dir)
            session.sub_agent_state = SubAgentState(
                sub_agent_type="Finder", sub_agent_desc="find things", sub_agent_prompt="prompt text"
            )
            session.parent_session_id = "parent-1"
            session.agent_type = "finder"
            session.spawn_kind = "subagent"
            session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("done"))])
            await session.wait_for_flush()

            store = get_store_for_path(project_dir)
            raw = store.load_meta("sub-1")
            assert raw is not None
            assert "sub_agent_state" not in raw
            loaded = Session.load_meta("sub-1", work_dir=project_dir)
            assert loaded.sub_agent_state is None
            assert loaded.parent_session_id == "parent-1"
            assert loaded.agent_type == "finder"
            assert loaded.spawn_kind == "subagent"
            await close_default_store()

        arun(_test())

    def test_legacy_sub_agent_state_meta_still_parses(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        store = _make_store(project_dir)
        sid = "legacy-sub"
        meta = _seed_meta(store, sid, project_dir)
        assert meta["id"] == sid
        assert store.update_meta(
            sid,
            {
                "sub_agent_state": {
                    "sub_agent_type": "Finder",
                    "sub_agent_desc": "find things",
                    "sub_agent_prompt": "prompt text",
                }
            },
        )

        loaded = Session.load_meta(sid, work_dir=project_dir)
        assert loaded.sub_agent_state is not None
        assert loaded.sub_agent_state.sub_agent_type == "Finder"
        assert loaded.sub_agent_state.sub_agent_prompt == "prompt text"


# =====================================================================
# History append notifications: the ledger's "disk grew" signal.
# =====================================================================


class TestHistoryAppendNotifications:
    def test_observer_reports_the_running_line_count(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        seen: list[tuple[str, int]] = []
        unregister = register_session_history_observer(lambda sid, count: seen.append((sid, count)))
        holder: dict[str, str] = {}

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            holder["id"] = session.id
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("one"))])
            await session.wait_for_flush()
            session.append_history(
                [
                    message.UserMessage(parts=message.text_parts_from_str("two")),
                    message.AssistantMessage(parts=message.text_parts_from_str("three")),
                ]
            )
            await session.wait_for_flush()

        try:
            arun(_test())
        finally:
            unregister()

        session_id = holder["id"]
        assert [entry for entry in seen if entry[0] == session_id] == [(session_id, 1), (session_id, 3)]
        store = get_store_for_path(project_dir)
        assert store.history_line_count(session_id) == 3
        assert count_file_lines(store.paths.events_file(session_id)) == 3
        arun(close_default_store())

    def test_scan_and_slice_follow_the_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The cached scan is re-taken after an append, and slices re-encode."""
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)
        holder: dict[str, str] = {}

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            holder["id"] = session.id
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("first"))])
            await session.wait_for_flush()
            store = get_store_for_path(project_dir)
            assert len(store.scan_history_lines(session.id).statuses) == 1
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("second"))])
            await session.wait_for_flush()
            scan = store.scan_history_lines(session.id)
            assert [status.status for status in scan.statuses] == ["active", "active"]
            encoded = store.encode_history_lines(session.id, 1, 2)
            assert len(encoded) == 1
            line_index, payload = encoded[0]
            assert line_index == 1
            assert payload is not None
            assert payload["type"] == "UserMessage"
            assert payload["data"]["parts"][0]["text"] == "second"

        arun(_test())
        arun(close_default_store())

    def test_count_file_lines_handles_a_missing_trailing_newline(self, tmp_path: Path) -> None:
        path = tmp_path / "events.jsonl"
        path.write_text("a\nb\nc", encoding="utf-8")
        assert count_file_lines(path) == 3
        assert count_file_lines(tmp_path / "absent.jsonl") == 0
