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

from klaude_code.protocol import llm_param, message
from klaude_code.protocol.models import (
    FileChangeSummary,
    FileStatus,
    SessionOwner,
    SessionRuntimeState,
    SubAgentState,
    TodoItem,
)
from klaude_code.session.session import Session
from klaude_code.session.store import JsonlSessionStore, build_meta_snapshot
from klaude_code.session.store_registry import close_default_store, get_store_for_path


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


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
                session_state=SessionRuntimeState.IDLE,
                archived=False,
                next_checkpoint_id=3,
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
            assert loaded.next_checkpoint_id == 3
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

    def test_load_meta_omits_history_but_keeps_user_messages(
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


def _make_store(work_dir: Path) -> JsonlSessionStore:
    # get_store_for_path caches per project key; close_default_store cleans up.
    return get_store_for_path(work_dir)


def _seed_meta(store: JsonlSessionStore, session_id: str, work_dir: Path, **overrides: Any) -> dict[str, Any]:
    meta = build_meta_snapshot(
        session_id=session_id,
        work_dir=work_dir,
        title=overrides.get("title", "seed title"),
        sub_agent_state=None,
        file_tracker={},
        file_change_summary=FileChangeSummary(),
        todos=[],
        user_messages=overrides.get("user_messages", ["hi"]),
        created_at=1000.0,
        updated_at=1000.0,
        messages_count=overrides.get("messages_count", 1),
        model_name=overrides.get("model_name", "seed-model"),
        session_state=overrides.get("session_state"),
        runtime_owner=None,
        runtime_owner_heartbeat_at=None,
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
            sub_agent_state=None,
            file_tracker={},
            file_change_summary=FileChangeSummary(),
            todos=[],
            user_messages=[],
            created_at=2000.0,
            updated_at=2000.0,
            messages_count=9,
            model_name=None,
            session_state=None,
            runtime_owner=None,
            runtime_owner_heartbeat_at=None,
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

    def test_history_append_preserves_concurrently_written_runtime_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """append_history's meta write re-reads and preserves runtime keys
        (session_state, runtime_owner, ...) written via persist_* helpers.

        This locks in the read-merge-write protection in _write_batch_sync for
        _RUNTIME_META_KEYS: a runtime_owner set independently is not clobbered
        by a subsequent history flush that carries no owner.
        """
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session(work_dir=project_dir)
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("seed"))])
            await session.wait_for_flush()

            owner = SessionOwner(runtime_id="rt-1", runtime_kind="web", pid=4321)
            Session.persist_runtime_owner(session.id, owner, project_dir)
            Session.persist_runtime_state(session.id, SessionRuntimeState.RUNNING, project_dir)

            # A subsequent history flush (which carries no runtime_owner in its
            # snapshot, since session.runtime_owner is still None) must NOT erase
            # the owner / state written above.
            session.append_history([message.UserMessage(parts=message.text_parts_from_str("more"))])
            await session.wait_for_flush()

            raw = json.loads(Session.paths(project_dir).meta_file(session.id).read_text(encoding="utf-8"))
            assert raw["session_state"] == SessionRuntimeState.RUNNING.value
            assert raw["runtime_owner"]["pid"] == 4321
            await close_default_store()

        arun(_test())


# =====================================================================
# Sub-agent meta excluded; round-trip of sub-agent-flagged session.
# =====================================================================


class TestSubAgentMetaRoundTrip:
    def test_sub_agent_state_roundtrips(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        project_dir = tmp_path / "proj"
        project_dir.mkdir()
        monkeypatch.chdir(project_dir)

        async def _test() -> None:
            session = Session.create(id="sub-1", work_dir=project_dir)
            session.sub_agent_state = SubAgentState(
                sub_agent_type="Finder", sub_agent_desc="find things", sub_agent_prompt="prompt text"
            )
            session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("done"))])
            await session.wait_for_flush()

            loaded = Session.load_meta("sub-1", work_dir=project_dir)
            assert loaded.sub_agent_state is not None
            assert loaded.sub_agent_state.sub_agent_type == "Finder"
            assert loaded.sub_agent_state.sub_agent_desc == "find things"
            assert loaded.sub_agent_state.sub_agent_prompt == "prompt text"
            await close_default_store()

        arun(_test())
