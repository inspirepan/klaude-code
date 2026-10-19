from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import login_cmd

pytestmark = pytest.mark.usefixtures("isolated_home")


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_login_command_passes_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    login_calls: list[str] = []

    def _execute_login(provider: str) -> bool:
        login_calls.append(provider)
        return True

    monkeypatch.setattr(login_cmd, "execute_login", _execute_login)

    cmd = login_cmd.LoginCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="chatgpt")))

    assert login_calls == ["chatgpt"]
    assert result.events is not None
    assert result.events[0].content == "Login flow completed."


def test_login_command_reports_cancelled_when_flow_declined(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())

    def _execute_login(provider: str) -> bool:
        return False

    monkeypatch.setattr(login_cmd, "execute_login", _execute_login)

    cmd = login_cmd.LoginCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="chatgpt")))

    assert result.events is not None
    assert result.events[0].content == "(cancelled)"
