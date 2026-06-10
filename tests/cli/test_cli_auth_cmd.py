from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from klaude_code.cli import auth_cmd


def test_cli_logout_without_provider_uses_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    selector_calls: list[tuple[bool, bool, str]] = []
    logout_calls: list[str] = []

    def _select_provider(
        *, include_api_keys: bool = True, configured_only: bool = False, prompt: str = ""
    ) -> str | None:
        selector_calls.append((include_api_keys, configured_only, prompt))
        return "codex"

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr("klaude_code.tui.command.auth_selector.select_provider", _select_provider)
    monkeypatch.setattr("klaude_code.app.auth_flow.execute_logout", _execute_logout)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert selector_calls == [(True, True, "Select provider to logout:")]
    assert logout_calls == ["codex"]


def test_cli_logout_cancelled_when_selector_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    logout_calls: list[str] = []

    def _select_provider(
        *, include_api_keys: bool = True, configured_only: bool = False, prompt: str = ""
    ) -> str | None:
        del include_api_keys, configured_only, prompt
        return None

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr("klaude_code.tui.command.auth_selector.select_provider", _select_provider)
    monkeypatch.setattr("klaude_code.app.auth_flow.execute_logout", _execute_logout)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert logout_calls == []


def test_cli_login_codex_passes_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls: list[tuple[str, str | None]] = []

    def _execute_login(provider: str, account_name: str | None = None) -> None:
        login_calls.append((provider, account_name))

    monkeypatch.setattr("klaude_code.app.auth_flow.execute_login", _execute_login)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "login", "codex", "--name", "work"])

    assert result.exit_code == 0
    assert login_calls == [("codex", "work")]


def test_cli_logout_codex_passes_account_name(monkeypatch: pytest.MonkeyPatch) -> None:
    logout_calls: list[tuple[str, str | None, bool]] = []

    def _execute_logout(provider: str, account_name: str | None = None, *, all_accounts: bool = False) -> None:
        logout_calls.append((provider, account_name, all_accounts))

    monkeypatch.setattr("klaude_code.app.auth_flow.execute_logout", _execute_logout)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "logout", "codex", "work"])

    assert result.exit_code == 0
    assert logout_calls == [("codex", "work", False)]


def test_cli_auth_switch_command(monkeypatch: pytest.MonkeyPatch) -> None:
    switch_calls: list[tuple[str, str | None]] = []

    def _execute_switch(provider: str, account_name: str | None = None) -> None:
        switch_calls.append((provider, account_name))

    monkeypatch.setattr("klaude_code.app.auth_flow.execute_switch", _execute_switch)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "switch", "codex", "work"])

    assert result.exit_code == 0
    assert switch_calls == [("codex", "work")]


def test_cli_auth_switch_defaults_to_codex_for_single_account_arg(monkeypatch: pytest.MonkeyPatch) -> None:
    switch_calls: list[tuple[str, str | None]] = []

    def _execute_switch(provider: str, account_name: str | None = None) -> None:
        switch_calls.append((provider, account_name))

    monkeypatch.setattr("klaude_code.app.auth_flow.execute_switch", _execute_switch)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "switch", "work"])

    assert result.exit_code == 0
    assert switch_calls == [("codex", "work")]
