from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from klaude_code.auth.xai.exceptions import XaiOAuthError
from klaude_code.auth.xai.oauth import CLIENT_ID, REFERRER, SCOPE, XaiDeviceCode, XaiOAuth
from klaude_code.auth.xai.token_manager import XaiAuthState, XaiTokenManager


class _Response:
    def __init__(self, status_code: int, data: dict[str, Any]):
        self.status_code = status_code
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


def test_login_requests_device_code_then_polls_and_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, str]] = []
    responses = iter(
        [
            _Response(
                200,
                {
                    "device_code": "device",
                    "user_code": "USER-CODE",
                    "verification_uri": "https://auth.x.ai/verify",
                    "verification_uri_complete": "https://auth.x.ai/verify?code=USER-CODE",
                    "expires_in": 300,
                    "interval": 5,
                },
            ),
            _Response(400, {"error": "authorization_pending"}),
            _Response(200, {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}),
        ]
    )

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            requests.append(data)
            return next(responses)

    clock = iter([1000.0, 1001.0, 1002.0])
    notified: list[XaiDeviceCode] = []
    auth_file = tmp_path / "klaude-auth.json"
    monkeypatch.setattr("klaude_code.auth.xai.oauth.httpx.Client", _Client)
    monkeypatch.setattr("klaude_code.auth.xai.oauth.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("klaude_code.auth.xai.oauth.time.time", lambda: 1000.0)
    monkeypatch.setattr("klaude_code.auth.xai.oauth.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("klaude_code.auth.xai.oauth.webbrowser.open", lambda _url: True)

    state = XaiOAuth(XaiTokenManager(auth_file=auth_file)).login(notifier=notified.append)

    assert requests[0] == {"client_id": CLIENT_ID, "scope": SCOPE, "referrer": REFERRER}
    assert notified[0].user_code == "USER-CODE"
    assert state.access_token == "access"
    persisted = XaiTokenManager(auth_file=auth_file).get_state()
    assert persisted is not None
    assert persisted.refresh_token == "refresh"


def test_refresh_keeps_old_refresh_token_when_omitted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = XaiTokenManager(auth_file=tmp_path / "klaude-auth.json")
    manager.save(XaiAuthState(access_token="old", refresh_token="old-refresh", expires_at=1))

    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response(200, {"access_token": "new", "expires_in": 3600})

    monkeypatch.setattr("klaude_code.auth.xai.oauth.httpx.Client", _Client)

    state = XaiOAuth(manager).refresh()

    assert state.access_token == "new"
    assert state.refresh_token == "old-refresh"


def test_login_rejects_non_https_verification_uri(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def post(self, *_args: object, **_kwargs: object) -> _Response:
            return _Response(200, {"device_code": "device", "user_code": "code", "verification_uri": "http://x.ai"})

    monkeypatch.setattr("klaude_code.auth.xai.oauth.httpx.Client", _Client)

    with pytest.raises(XaiOAuthError, match="must use HTTPS"):
        XaiOAuth(XaiTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()
