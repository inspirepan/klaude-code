from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import copy_cmd

pytestmark = pytest.mark.usefixtures("isolated_home")


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_copy_command_selects_assistant_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    first_answer = "first answer " * 20
    second_answer = "second answer " * 20
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hi")),
        message.AssistantMessage(parts=message.text_parts_from_str(first_answer)),
        message.AssistantMessage(parts=message.text_parts_from_str(second_answer)),
    ]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)
    monkeypatch.setattr(copy_cmd, "_select_copy_entry_sync", lambda items: items[1].value)

    cmd = copy_cmd.CopyCommand()
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == [first_answer.strip()]


def test_copy_command_includes_btw_answers_in_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    side_answer = "side answer " * 30
    main_answer = "main answer " * 30
    session.conversation_history = [
        message.AssistantMessage(parts=message.text_parts_from_str(main_answer)),
        message.SideQuestionEntry(question="side question", answer=side_answer),
    ]
    copied: list[str] = []
    selected_items: list[copy_cmd.SelectItem[int]] = []

    def _select(items: list[copy_cmd.SelectItem[int]]) -> int | None:
        selected_items.extend(items)
        return items[0].value

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", copied.append)
    monkeypatch.setattr(copy_cmd, "_select_copy_entry_sync", _select)

    result = arun(copy_cmd.CopyCommand().run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == [side_answer.strip()]
    assert [item.value for item in selected_items] == [1, 0]
    preview = "".join(text for _, text in selected_items[0].title)
    assert preview.count("\n") == 3
    assert "assistant" not in preview
    assert "btw" not in preview
    assert "side answer" in preview
    assert all(style == "class:msg class:accent.magenta" for style, _ in selected_items[0].title[1:])
    assert all(style == "class:msg" for style, _ in selected_items[1].title[1:])
    assert result.events is not None


def test_copy_preview_uses_two_terminal_width_aware_lines() -> None:
    first, second = copy_cmd._preview_lines("甲" * 25, width=20)

    assert first == "甲" * 10
    assert second == "甲" * 9 + "…"


def test_copy_selector_only_includes_responses_longer_than_threshold() -> None:
    history = [
        message.AssistantMessage(parts=message.text_parts_from_str("a" * 200)),
        message.AssistantMessage(parts=message.text_parts_from_str("b" * 201)),
    ]

    items = copy_cmd._build_copy_items(history)

    assert [item.value for item in items] == [1]


def test_copy_command_ignores_assistant_images_without_text(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [
        message.AssistantMessage(
            parts=[
                *message.text_parts_from_str(""),
                message.ImageFilePart(file_path="/tmp/foo.png"),
            ]
        )
    ]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == []
    assert result.events is not None


def test_copy_command_uses_last_assistant_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("do stuff")),
        message.AssistantMessage(parts=message.text_parts_from_str("before")),
        message.ToolResultMessage(call_id="c0", tool_name="Bash", status="success", output_text="ok"),
        message.AssistantMessage(parts=message.text_parts_from_str("after")),
    ]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="1")))

    assert copied == ["after"]


def test_copy_command_nth_latest(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [
        message.AssistantMessage(parts=message.text_parts_from_str("a1")),
        message.UserMessage(parts=message.text_parts_from_str("q")),
        message.AssistantMessage(parts=message.text_parts_from_str("a2")),
        message.AssistantMessage(parts=message.text_parts_from_str("a3")),
    ]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="1")))
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="2")))
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="3")))

    assert copied == ["a3", "a2", "a1"]


def test_copy_command_invalid_n(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [message.AssistantMessage(parts=message.text_parts_from_str("a1"))]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="abc")))
    assert copied == []
    assert result.events is not None

    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="5")))
    assert copied == []
    assert result.events is not None


def test_copy_command_no_assistant_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [message.UserMessage(parts=message.text_parts_from_str("hi"))]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == []
    assert result.events is not None
