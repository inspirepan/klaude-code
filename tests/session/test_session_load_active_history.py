from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

from klaude_code.protocol import message
from klaude_code.protocol.models import Usage
from klaude_code.session.session import Session


def arun[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _text(item: message.HistoryEvent) -> str | None:
    if isinstance(item, message.UserMessage | message.AssistantMessage | message.DeveloperMessage):
        return message.join_text_parts(item.parts)
    return None


def test_load_applies_rewind_semantics(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("hello"))])
        checkpoint_id = session.create_checkpoint()
        session.append_history(
            [
                message.AssistantMessage(parts=message.text_parts_from_str("discarded assistant")),
                message.UserMessage(parts=message.text_parts_from_str("discarded user")),
            ]
        )

        rewind_entry = session.revert_to_checkpoint(checkpoint_id, "keep only hello", "test rewind")
        session.append_history([rewind_entry])
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)

        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "UserMessage",
            "DeveloperMessage",
            "RewindEntry",
        ]
        assert [_text(item) for item in loaded.conversation_history] == [
            "hello",
            f"<system-reminder>Checkpoint {checkpoint_id}</system-reminder>",
            None,
        ]

        llm_history = loaded.get_llm_history()
        assert [type(item).__name__ for item in llm_history] == [
            "UserMessage",
            "DeveloperMessage",
            "DeveloperMessage",
        ]
        assert [_text(item) for item in llm_history] == [
            "hello",
            f"<system-reminder>Checkpoint {checkpoint_id}</system-reminder>",
            "<system-reminder>After this, some operations were performed and context was refined via Rewind. "
            "Rationale: test rewind. Summary: keep only hello. Please continue.</system-reminder>",
        ]

    arun(_test())


def test_load_keeps_only_latest_compaction_prefix(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("old user")),
                message.AssistantMessage(parts=message.text_parts_from_str("old assistant")),
                message.UserMessage(parts=message.text_parts_from_str("kept user")),
                message.AssistantMessage(parts=message.text_parts_from_str("kept assistant")),
            ]
        )
        session.append_history([message.CompactionEntry(summary="summary", first_kept_index=2)])
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("after compact"))])
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)

        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "CompactionEntry",
            "UserMessage",
            "AssistantMessage",
            "UserMessage",
        ]
        first_item = loaded.conversation_history[0]
        assert isinstance(first_item, message.CompactionEntry)
        assert first_item.summary == "summary"
        assert first_item.first_kept_index == 1
        assert [_text(item) for item in loaded.conversation_history[1:]] == [
            "kept user",
            "kept assistant",
            "after compact",
        ]

        llm_history = loaded.get_llm_history()
        assert [_text(item) for item in llm_history] == [
            "summary",
            "kept user",
            "kept assistant",
            "after compact",
        ]

    arun(_test())


def test_retract_removes_message_live_and_on_reload(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("hello")),
                message.AssistantMessage(
                    parts=message.text_parts_from_str("hi"),
                    usage=Usage(input_tokens=10, output_tokens=2),
                ),
                message.UserMessage(parts=message.text_parts_from_str("retract me")),
                message.InterruptEntry(show_notice=False),
            ]
        )
        assert session.last_request_usage is not None

        assert session.retract_last_user_message("retract me") is True
        await session.wait_for_flush()

        expected_types = [
            "UserMessage",
            "AssistantMessage",
            "InterruptEntry",
            "RetractEntry",
        ]
        assert [type(item).__name__ for item in session.conversation_history] == expected_types
        assert session.user_messages == ["hello"]
        assert session.last_request_usage is None

        loaded = Session.load(session.id, work_dir=project_dir)
        assert [type(item).__name__ for item in loaded.conversation_history] == expected_types
        assert loaded.user_messages == ["hello"]
        assert not any(
            isinstance(item, message.UserMessage) and _text(item) == "retract me" for item in loaded.get_llm_history()
        )

    arun(_test())


def test_retract_keeps_the_turns_other_appends(isolated_home: Path, tmp_path: Path) -> None:
    """Only the user message goes; attachment developer messages stay so
    file-tracker loaded flags remain consistent with LLM context."""
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("retract me")),
                message.DeveloperMessage(parts=message.text_parts_from_str("attachment payload")),
            ]
        )

        assert session.retract_last_user_message("retract me") is True
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "DeveloperMessage",
            "RetractEntry",
        ]
        assert _text(loaded.conversation_history[0]) == "attachment payload"

    arun(_test())


def test_retract_matches_a_message_carrying_images(isolated_home: Path, tmp_path: Path) -> None:
    """TUI messages carry images as ``[image path]`` markers inside the text,
    plus image parts extracted at submit. The anchor matches on the text
    (markers included, image parts ignored), so restoring the text into the
    input box restores the images too — they re-extract on the next submit."""
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        text_with_marker = "look at [image /tmp/shot.png]"
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

        assert session.retract_last_user_message(text_with_marker) is True
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        assert not any(isinstance(item, message.UserMessage) for item in loaded.conversation_history)
        retract_entries = [item for item in loaded.conversation_history if isinstance(item, message.RetractEntry)]
        assert len(retract_entries) == 1
        assert retract_entries[0].retracted_text == text_with_marker

    arun(_test())


def test_retract_refuses_a_mismatched_anchor(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("something else"))])

        assert session.retract_last_user_message("retract me") is False
        assert session.user_messages == ["something else"]
        assert not any(isinstance(item, message.RetractEntry) for item in session.conversation_history)

    arun(_test())


def test_load_ignores_a_retract_entry_whose_anchor_drifted(isolated_home: Path, tmp_path: Path) -> None:
    """A hand-edited or corrupted stream must not lose the wrong message."""
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history(
            [
                message.UserMessage(parts=message.text_parts_from_str("kept")),
                message.RetractEntry(retracted_text="never sent"),
            ]
        )
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)
        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "UserMessage",
            "RetractEntry",
        ]
        assert loaded.user_messages == ["kept"]

    arun(_test())


def test_load_replays_rewind_before_dropping_compacted_prefix(isolated_home: Path, tmp_path: Path) -> None:
    del isolated_home
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    async def _test() -> None:
        session = Session.create(work_dir=project_dir)
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("before checkpoint"))])
        checkpoint_id = session.create_checkpoint()
        session.append_history(
            [
                message.AssistantMessage(parts=message.text_parts_from_str("before compaction")),
                message.UserMessage(parts=message.text_parts_from_str("also discarded")),
            ]
        )
        session.append_history([message.CompactionEntry(summary="summary", first_kept_index=2)])
        session.append_history([message.UserMessage(parts=message.text_parts_from_str("after compaction"))])

        rewind_entry = session.revert_to_checkpoint(checkpoint_id, "rewind to checkpoint", "test rewind")
        session.append_history([rewind_entry])
        await session.wait_for_flush()

        loaded = Session.load(session.id, work_dir=project_dir)

        assert [type(item).__name__ for item in loaded.conversation_history] == [
            "UserMessage",
            "DeveloperMessage",
            "RewindEntry",
        ]
        assert [_text(item) for item in loaded.conversation_history] == [
            "before checkpoint",
            f"<system-reminder>Checkpoint {checkpoint_id}</system-reminder>",
            None,
        ]
        assert not any(isinstance(item, message.CompactionEntry) for item in loaded.conversation_history)

    arun(_test())
