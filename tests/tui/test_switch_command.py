from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from klaude_code.protocol import message
from klaude_code.session.session import Session
from klaude_code.tui.command import switch_cmd

pytestmark = pytest.mark.usefixtures("isolated_home")


class _DummyAgent:
    def __init__(self, session: Session):
        self.session = session
        self.profile = None

    def get_llm_client(self) -> Any:  # pragma: no cover
        raise NotImplementedError


def arun(coro: Any) -> Any:
    return asyncio.run(coro)


def test_switch_command_without_args_prompts_codex(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    switch_calls: list[tuple[str, str | None]] = []

    def _execute_switch(provider: str, account_name: str | None = None) -> None:
        switch_calls.append((provider, account_name))

    monkeypatch.setattr(switch_cmd, "execute_switch", _execute_switch)

    cmd = switch_cmd.SwitchCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="")))

    assert switch_calls == [("codex", None)]
    assert result.events is not None
    assert result.events[0].content == "Switch flow completed."


def test_switch_command_defaults_single_arg_to_codex_account(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    switch_calls: list[tuple[str, str | None]] = []

    def _execute_switch(provider: str, account_name: str | None = None) -> None:
        switch_calls.append((provider, account_name))

    monkeypatch.setattr(switch_cmd, "execute_switch", _execute_switch)

    cmd = switch_cmd.SwitchCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="work")))

    assert switch_calls == [("codex", "work")]
    assert result.events is not None
    assert result.events[0].content == "Switch flow completed."


def test_switch_command_accepts_provider_and_account(monkeypatch: pytest.MonkeyPatch) -> None:
    session = Session.create(work_dir=Path.cwd())
    switch_calls: list[tuple[str, str | None]] = []

    def _execute_switch(provider: str, account_name: str | None = None) -> None:
        switch_calls.append((provider, account_name))

    monkeypatch.setattr(switch_cmd, "execute_switch", _execute_switch)

    cmd = switch_cmd.SwitchCommand()
    result = arun(cmd.run(_DummyAgent(session), message.UserInputPayload(text="codex work")))

    assert switch_calls == [("codex", "work")]
    assert result.events is not None
    assert result.events[0].content == "Switch flow completed."
