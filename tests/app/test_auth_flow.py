from __future__ import annotations

from typing import Any, ClassVar

import pytest

from klaude_code.app import auth_flow
from klaude_code.auth.codex.token_manager import CodexAuthState


class _FakeCodexTokenManager:
    created_names: ClassVar[list[str | None]] = []
    accounts: ClassVar[list[CodexAuthState]] = [
        CodexAuthState(
            access_token="access-personal",
            refresh_token="refresh-personal",
            expires_at=4102444800,
            account_id="acct-personal",
            name="personal",
        ),
        CodexAuthState(
            access_token="access-work",
            refresh_token="refresh-work",
            expires_at=4102444800,
            account_id="acct-work",
            name="work",
        ),
    ]
    active = "work"

    def __init__(self, auth_file: Any = None, account_name: str | None = None):
        del auth_file
        self.account_name = account_name
        self.created_names.append(account_name)

    def list_accounts(self) -> list[CodexAuthState]:
        return self.accounts

    def get_active_account_name(self) -> str | None:
        return self.active

    def is_logged_in(self) -> bool:
        return self.get_state() is not None

    def get_state(self) -> CodexAuthState | None:
        target = self.account_name or self.active
        return next((state for state in self.accounts if state.name == target), None)


def test_execute_codex_login_lists_existing_accounts_before_new_login(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[Any] = []

    class _FakeCodexOAuth:
        def __init__(self, token_manager: _FakeCodexTokenManager):
            del token_manager

        def login(self, account_name: str | None = None) -> CodexAuthState:
            raise AssertionError(f"OAuth should not start for account {account_name}")

    _FakeCodexTokenManager.created_names = []
    monkeypatch.setattr("klaude_code.auth.codex.token_manager.CodexTokenManager", _FakeCodexTokenManager)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.CodexOAuth", _FakeCodexOAuth)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: False)
    monkeypatch.setattr(auth_flow, "log", lambda message: logs.append(message))

    auth_flow.execute_login("codex")

    assert _FakeCodexTokenManager.created_names == [None]
    assert "You already have Codex accounts:" in logs
    assert "  work  acct-wor… active" in logs


def test_execute_codex_login_prompts_for_new_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls: list[str | None] = []

    class _FakeCodexOAuth:
        def __init__(self, token_manager: _FakeCodexTokenManager):
            self.token_manager = token_manager

        def login(self, account_name: str | None = None) -> CodexAuthState:
            login_calls.append(account_name)
            return CodexAuthState(
                access_token="access-new",
                refresh_token="refresh-new",
                expires_at=4102444800,
                account_id="acct-new",
                name=account_name or "default",
            )

    _FakeCodexTokenManager.created_names = []
    monkeypatch.setattr("klaude_code.auth.codex.token_manager.CodexTokenManager", _FakeCodexTokenManager)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.CodexOAuth", _FakeCodexOAuth)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: True)
    monkeypatch.setattr(auth_flow.typer, "prompt", lambda _prompt: "new")
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    auth_flow.execute_login("codex")

    assert _FakeCodexTokenManager.created_names == [None, "new"]
    assert login_calls == ["new"]