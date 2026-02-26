from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import copy_cmd


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_copy_command_copies_last_assistant_message(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hi")),
        message.AssistantMessage(parts=message.text_parts_from_str("a1")),
        message.AssistantMessage(parts=message.text_parts_from_str("a2")),
    ]

    copied: list[str] = []

    def _copy(text: str) -> None:
        copied.append(text)

    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", _copy)

    cmd = copy_cmd.CopyCommand()
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == ["a2"]


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
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == ["after"]


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
