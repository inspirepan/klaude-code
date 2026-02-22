from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import logout_cmd


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_logout_command_uses_selector_when_provider_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    selector_calls: list[tuple[bool, str]] = []
    logout_calls: list[str] = []

    def _select_provider(*, include_api_keys: bool = True, prompt: str = "") -> str | None:
        selector_calls.append((include_api_keys, prompt))
        return "claude"

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr(logout_cmd, "select_provider", _select_provider)
    monkeypatch.setattr(logout_cmd, "execute_logout", _execute_logout)

    cmd = logout_cmd.LogoutCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert selector_calls == [(False, "Select provider to logout:")]
    assert logout_calls == ["claude"]
    assert result.events is not None
    assert result.events[0].content == "Logout flow completed."


def test_logout_command_returns_cancelled_when_selector_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    logout_calls: list[str] = []

    def _select_provider(*, include_api_keys: bool = True, prompt: str = "") -> str | None:
        del include_api_keys, prompt
        return None

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr(logout_cmd, "select_provider", _select_provider)
    monkeypatch.setattr(logout_cmd, "execute_logout", _execute_logout)

    cmd = logout_cmd.LogoutCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert logout_calls == []
    assert result.events is not None
    assert result.events[0].content == "(cancelled)"
