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

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_login_command_passes_codex_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    login_calls: list[tuple[str, str | None]] = []

    def _execute_login(provider: str, account_name: str | None = None) -> None:
        login_calls.append((provider, account_name))

    monkeypatch.setattr(login_cmd, "execute_login", _execute_login)

    cmd = login_cmd.LoginCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="codex --name work")))

    assert login_calls == [("codex", "work")]
    assert result.events is not None
    assert result.events[0].content == "Login flow completed."


def test_login_command_accepts_codex_account_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    login_calls: list[tuple[str, str | None]] = []

    def _execute_login(provider: str, account_name: str | None = None) -> None:
        login_calls.append((provider, account_name))

    monkeypatch.setattr(login_cmd, "execute_login", _execute_login)

    cmd = login_cmd.LoginCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="codex work")))

    assert login_calls == [("codex", "work")]
    assert result.events is not None
    assert result.events[0].content == "Login flow completed."
