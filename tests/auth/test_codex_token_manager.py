from __future__ import annotations

import json
from pathlib import Path

import pytest

from klaude_code.auth.codex.oauth import CodexOAuth
from klaude_code.auth.codex.token_manager import CodexAuthState, CodexTokenManager


def _state(name: str, account_id: str) -> CodexAuthState:
    return CodexAuthState(
        access_token=f"access-{name}",
        refresh_token=f"refresh-{name}",
        expires_at=4102444800,
        account_id=account_id,
        name=name,
    )


def test_codex_token_manager_reads_legacy_single_account(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "codex": {
                    "access_token": "access",
                    "refresh_token": "refresh",
                    "expires_at": 4102444800,
                    "account_id": "acct-legacy",
                }
            }
        )
    )

    manager = CodexTokenManager(auth_file=auth_file)

    state = manager.get_state()
    assert state is not None
    assert state.name == "default"
    assert state.account_id == "acct-legacy"
    assert manager.get_active_account_name() == "default"


def test_codex_token_manager_saves_and_switches_accounts(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = CodexTokenManager(auth_file=auth_file)

    manager.save(_state("personal", "acct-personal"), account_name="personal")
    manager.save(_state("work", "acct-work"), account_name="work")

    assert manager.get_active_account_name() == "work"
    assert [state.name for state in manager.list_accounts()] == ["personal", "work"]

    active_state = manager.set_active_account("personal")
    assert active_state.account_id == "acct-personal"
    reloaded_state = CodexTokenManager(auth_file=auth_file).get_state()
    assert reloaded_state is not None
    assert reloaded_state.account_id == "acct-personal"


def test_codex_token_manager_deletes_active_account_without_dropping_others(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = CodexTokenManager(auth_file=auth_file)
    manager.save(_state("personal", "acct-personal"), account_name="personal")
    manager.save(_state("work", "acct-work"), account_name="work")

    manager.delete("work")

    remaining = manager.list_accounts()
    assert [state.name for state in remaining] == ["personal"]
    assert manager.get_active_account_name() == "personal"
    active_state = manager.get_state()
    assert active_state is not None
    assert active_state.account_id == "acct-personal"


def test_codex_oauth_refresh_preserves_active_account_slot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = CodexTokenManager(auth_file=auth_file)
    manager.save(_state("personal", "acct-personal"), account_name="personal")
    manager.save(
        _state("work", "acct-work").model_copy(update={"expires_at": 1}),
        account_name="work",
    )

    class _Response:
        status_code = 200

        def json(self) -> dict[str, object]:
            return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}

    class _Client:
        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response()

    monkeypatch.setattr("klaude_code.auth.codex.oauth.httpx.Client", _Client)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.extract_account_id", lambda _token: "acct-work-new")

    refreshed = CodexOAuth(manager).refresh()

    assert refreshed.name == "work"
    assert refreshed.account_id == "acct-work-new"
    assert manager.get_active_account_name() == "work"
    assert [state.name for state in manager.list_accounts()] == ["personal", "work"]
    work_state = CodexTokenManager(auth_file=auth_file, account_name="work").get_state()
    assert work_state is not None
    assert work_state.access_token == "new-access"
