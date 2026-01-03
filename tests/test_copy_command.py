from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

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


def test_copy_command_copies_last_assistant_message(monkeypatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [
        message.UserMessage(parts=message.text_parts_from_str("hi")),
        message.AssistantMessage(parts=message.text_parts_from_str("a1")),
        message.AssistantMessage(parts=message.text_parts_from_str("a2")),
    ]

    copied: list[str] = []
    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", lambda text: copied.append(text))

    cmd = copy_cmd.CopyCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == ["a2"]
    assert result.persist_user_input is False
    assert result.persist_events is False


def test_copy_command_formats_saved_images(monkeypatch) -> None:
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
    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", lambda text: copied.append(text))

    cmd = copy_cmd.CopyCommand()
    _ = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == ["Saved image at /tmp/foo.png"]


def test_copy_command_no_assistant_message(monkeypatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    session.conversation_history = [message.UserMessage(parts=message.text_parts_from_str("hi"))]

    copied: list[str] = []
    monkeypatch.setattr(copy_cmd, "copy_to_clipboard", lambda text: copied.append(text))

    cmd = copy_cmd.CopyCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert copied == []
    assert result.events is not None
