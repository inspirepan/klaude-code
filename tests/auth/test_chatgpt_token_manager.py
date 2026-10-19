from __future__ import annotations

import json
from pathlib import Path

import pytest

from klaude_code.auth.chatgpt.oauth import RESOURCE, SCOPE, ChatGPTOAuth
from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState, ChatGPTTokenManager

CLIENT_ID = "oaiapp_saved"


def _state() -> ChatGPTAuthState:
    return ChatGPTAuthState(
        access_token="access",
        refresh_token="refresh",
        expires_at=4102444800,
        client_id=CLIENT_ID,
        scopes=[str(part) for part in SCOPE.split()],
    )


def test_token_manager_saves_and_loads_single_account(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = ChatGPTTokenManager(auth_file=auth_file)

    manager.save(_state())

    reloaded = ChatGPTTokenManager(auth_file=auth_file).get_state()
    assert reloaded is not None
    assert reloaded.access_token == "access"
    assert reloaded.client_id == CLIENT_ID
    assert reloaded.scopes == SCOPE.split()


def test_token_manager_delete_keeps_device_id(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = ChatGPTTokenManager(auth_file=auth_file)
    device_id = manager.get_or_create_device_id()
    manager.save(_state())

    manager.delete()

    assert manager.get_state() is None
    assert json.loads(auth_file.read_text()) == {"chatgpt_device_id": device_id}


def test_device_id_is_stable(tmp_path: Path) -> None:
    auth_file = tmp_path / "klaude-auth.json"

    first = ChatGPTTokenManager(auth_file=auth_file).get_or_create_device_id()
    second = ChatGPTTokenManager(auth_file=auth_file).get_or_create_device_id()

    assert first == second
    assert json.loads(auth_file.read_text())["chatgpt_device_id"] == first


def test_refresh_keeps_refresh_token_when_response_omits_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    manager = ChatGPTTokenManager(auth_file=auth_file)
    manager.save(_state().model_copy(update={"expires_at": 1}))

    requests: list[dict[str, str]] = []

    class _Response:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"access_token": "new-access", "expires_in": 3600, "scope": SCOPE}

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            requests.append(data)
            return _Response()

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

    refreshed = ChatGPTOAuth(manager).refresh()

    assert requests == [
        {
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "refresh_token": "refresh",
            "resource": RESOURCE,
        }
    ]
    assert refreshed.access_token == "new-access"
    assert refreshed.refresh_token == "refresh"
    assert refreshed.client_id == CLIENT_ID


def test_refresh_failure_suggests_relogin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from klaude_code.auth.chatgpt.exceptions import ChatGPTTokenExpiredError

    auth_file = tmp_path / "klaude-auth.json"
    manager = ChatGPTTokenManager(auth_file=auth_file)
    manager.save(_state().model_copy(update={"expires_at": 1}))

    class _Response:
        status_code = 400
        text = '{"error": {"code": "refresh_token_invalidated"}}'

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            del data
            return _Response()

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

    with pytest.raises(ChatGPTTokenExpiredError) as exc_info:
        ChatGPTOAuth(manager).refresh()

    message = str(exc_info.value)
    assert "refresh_token_invalidated" in message
    assert "klaude auth login chatgpt" in message
