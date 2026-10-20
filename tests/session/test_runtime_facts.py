from __future__ import annotations

import asyncio
from pathlib import Path

from klaude_code.protocol import message
from klaude_code.protocol.models.session_status import SessionControl
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path


def test_old_metadata_preserves_history_without_guessing_a_turn_result(tmp_path: Path) -> None:
    async def seed() -> Session:
        session = Session.create(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("old conversation"))])
        await session.wait_for_flush()
        return session

    session = asyncio.run(seed())
    store = get_store_for_path(tmp_path)
    assert store.update_meta(
        session.id,
        {"runtime": None, "headless_completed_turn_id": "old-input", "headless_failed": True},
    )

    loaded = Session.load(session.id, tmp_path)

    assert loaded.user_messages == ["old conversation"]
    assert loaded.runtime.last_turn is None
    assert loaded.runtime.completed_input_id == "old-input"
    assert loaded.runtime.error is not None
    loaded.persist_runtime()
    raw = store.load_meta(session.id)
    assert raw is not None
    assert "headless_failed" not in raw and "headless_completed_turn_id" not in raw
    assert raw["runtime"]["completed_input_id"] == "old-input"


def test_legacy_pending_input_is_retained_but_not_assumed_unstarted(tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    session.ensure_meta_exists()
    pending = message.QueuedUserInput(id="legacy", input=message.UserInputPayload(text="do not replay"))
    assert get_store_for_path(tmp_path).update_meta(
        session.id,
        {"runtime": None, "headless_queued_turn": pending.model_dump(mode="json")},
    )

    loaded = Session.load_meta(session.id, tmp_path)

    assert loaded.headless_queued_turn == pending
    assert loaded.runtime.control == SessionControl(paused=True, reason="legacy_execution_unknown")
    assert loaded.runtime.last_turn is None


def test_queued_history_snapshot_does_not_overwrite_newer_runtime_facts(tmp_path: Path) -> None:
    async def run() -> None:
        session = Session.create(work_dir=tmp_path)
        session.ensure_meta_exists()
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("new input"))])
        session.begin_turn("turn")
        session.finish_turn("interrupted", reason="user_interrupt")
        session.runtime.control = SessionControl(paused=True, reason="user_interrupt")
        session.persist_runtime()
        await session.wait_for_flush()

        loaded = Session.load(session.id, tmp_path)
        assert loaded.runtime == session.runtime
        assert loaded.runtime.last_turn is not None and loaded.runtime.last_turn.result == "interrupted"
        assert loaded.user_messages == ["new input"]

    asyncio.run(run())


def test_input_ack_does_not_replace_newer_turn_or_active_execution(tmp_path: Path) -> None:
    session = Session.create(work_dir=tmp_path)
    session.begin_turn("first")
    session.finish_turn("interrupted")
    session.begin_turn("next")

    assert Session.persist_headless_completed_turn(session.id, tmp_path, turn_id="first")

    loaded = Session.load_meta(session.id, tmp_path)
    assert loaded.runtime.completed_input_id == "first"
    assert loaded.runtime.active_turn is not None and loaded.runtime.active_turn.id == "next"
    assert loaded.runtime.last_turn is not None and loaded.runtime.last_turn.result == "interrupted"
