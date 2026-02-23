from __future__ import annotations

import pytest
import typer
from typer.testing import CliRunner

from klaude_code.cli import auth_cmd


def test_cli_logout_without_provider_uses_selector(monkeypatch: pytest.MonkeyPatch) -> None:
    selector_calls: list[tuple[bool, str]] = []
    logout_calls: list[str] = []

    def _select_provider(*, include_api_keys: bool = True, prompt: str = "") -> str | None:
        selector_calls.append((include_api_keys, prompt))
        return "copilot"

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr(auth_cmd, "select_provider", _select_provider)
    monkeypatch.setattr(auth_cmd, "execute_logout", _execute_logout)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert selector_calls == [(False, "Select provider to logout:")]
    assert logout_calls == ["copilot"]


def test_cli_logout_cancelled_when_selector_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    logout_calls: list[str] = []

    def _select_provider(*, include_api_keys: bool = True, prompt: str = "") -> str | None:
        del include_api_keys, prompt
        return None

    def _execute_logout(provider: str) -> None:
        logout_calls.append(provider)

    monkeypatch.setattr(auth_cmd, "select_provider", _select_provider)
    monkeypatch.setattr(auth_cmd, "execute_logout", _execute_logout)

    app = typer.Typer()
    auth_cmd.register_auth_commands(app)
    result = CliRunner().invoke(app, ["auth", "logout"])

    assert result.exit_code == 0
    assert logout_calls == []
