from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from klaude_code.core.backtrack import BacktrackManager
from klaude_code.core.tool.backtrack.backtrack_tool import BacktrackTool
from klaude_code.core.tool.context import TodoContext, ToolContext
from klaude_code.protocol import message
from klaude_code.session.session import Session, close_default_store


def arun(coro: object) -> object:
    return asyncio.run(coro)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _isolate_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir(exist_ok=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setattr(Path, "home", lambda: fake_home)


def _tool_context(backtrack_manager: BacktrackManager | None) -> ToolContext:
    todo_context = TodoContext(get_todos=lambda: [], set_todos=lambda todos: None)
    return ToolContext(file_tracker={}, todo_context=todo_context, session_id="test", backtrack_manager=backtrack_manager)


def test_backtrack_manager_send_and_fetch() -> None:
    manager = BacktrackManager()
    manager.set_n_checkpoints(2)
    manager.register_checkpoint(0, "first")
    manager.register_checkpoint(1, "")

    result = manager.send_backtrack(1, "note", "test rationale")
    assert result == "Backtrack scheduled"

    pending = manager.fetch_pending()
    assert pending is not None
    assert pending.checkpoint_id == 1
    assert pending.note == "note"
    assert pending.rationale == "test rationale"
    assert manager.fetch_pending() is None


def test_backtrack_manager_rejects_invalid_checkpoint() -> None:
    manager = BacktrackManager()
    manager.set_n_checkpoints(2)
    manager.register_checkpoint(0, "first")

    with pytest.raises(ValueError):
        manager.send_backtrack(-1, "note", "rationale")

    with pytest.raises(ValueError):
        manager.send_backtrack(2, "note", "rationale")

    with pytest.raises(ValueError):
        manager.send_backtrack(1, "note", "rationale")


def test_session_revert_to_checkpoint(tmp_path: Path) -> None:
    async def _test() -> None:
        session = Session(work_dir=tmp_path)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        checkpoint_id = session.create_checkpoint()
        session.append_history([message.AssistantMessage(parts=message.text_parts_from_str("hi"))])

        entry = session.revert_to_checkpoint(checkpoint_id, "note", "test rationale")

        assert entry.checkpoint_id == checkpoint_id
        assert entry.note == "note"
        assert entry.rationale == "test rationale"
        assert entry.original_user_message == "hello"
        assert entry.reverted_from_index == 3
        assert len(session.conversation_history) == 2
        assert session.next_checkpoint_id == checkpoint_id + 1
        assert session.user_messages == ["hello"]

        await close_default_store()

    arun(_test())


def test_backtrack_tool_success() -> None:
    async def _test() -> None:
        manager = BacktrackManager()
        manager.set_n_checkpoints(1)
        manager.register_checkpoint(0, "hello")

        result = await BacktrackTool.call('{"checkpoint_id": 0, "note": "keep", "rationale": "test"}', _tool_context(manager))
        assert result.status == "success"
        assert "Backtrack scheduled" in result.output_text

        await close_default_store()

    arun(_test())


def test_backtrack_tool_rejects_missing_manager() -> None:
    async def _test() -> None:
        result = await BacktrackTool.call('{"checkpoint_id": 0, "note": "keep", "rationale": "test"}', _tool_context(None))
        assert result.status == "error"
        assert "Backtrack is not available" in result.output_text

        await close_default_store()

    arun(_test())


def test_backtrack_tool_invalid_args() -> None:
    async def _test() -> None:
        manager = BacktrackManager()
        result = await BacktrackTool.call("not-json", _tool_context(manager))
        assert result.status == "error"
        assert "Invalid arguments" in result.output_text

        await close_default_store()

    arun(_test())
