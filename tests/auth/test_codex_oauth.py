from __future__ import annotations

import base64
import json
import socket
import time
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from klaude_code.auth.codex.exceptions import CodexOAuthError
from klaude_code.auth.codex.oauth import (
    TOKEN_REQUEST_CONNECT_TIMEOUTS,
    CodexOAuth,
    OAuthCallbackHandler,
    post_token_request,
)
from klaude_code.auth.codex.token_manager import CodexTokenManager


class _Response:
    def __init__(self, status_code: int, data: dict[str, Any]):
        self.status_code = status_code
        self._data = data

    def json(self) -> dict[str, Any]:
        return self._data


def _access_token(account_id: str) -> str:
    claims = {"https://api.openai.com/auth": {"chatgpt_account_id": account_id}}
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{payload}.signature"


class _CallbackServer:
    """Stand in for the local HTTP server the browser is redirected to."""

    def __init__(self, state_of: Any, resolve_after: int | None) -> None:
        self.state_of = state_of
        self.resolve_after = resolve_after
        self.requests: list[str] = []
        self.timeout: float | None = None
        self.closed = False

    def handle_request(self) -> None:
        self.requests.append("request")
        if self.resolve_after is None or len(self.requests) < self.resolve_after:
            return
        OAuthCallbackHandler.code = "auth-code"
        OAuthCallbackHandler.state = self.state_of()
        OAuthCallbackHandler.resolved = True

    def server_close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_callback_handler() -> None:
    OAuthCallbackHandler.code = None
    OAuthCallbackHandler.state = None
    OAuthCallbackHandler.error = None
    OAuthCallbackHandler.resolved = False


def test_login_waits_for_callback_then_exchanges_and_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, str]] = []
    opened: list[str] = []
    servers: list[_CallbackServer] = []
    auth_file = tmp_path / "klaude-auth.json"

    def _state_from_authorize_url() -> str | None:
        return parse_qs(urlparse(opened[0]).query)["state"][0]

    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        # The first request is noise (favicon, stale tab), the second is the redirect.
        server = _CallbackServer(_state_from_authorize_url, 2)
        servers.append(server)
        return server

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, data: dict[str, str]) -> _Response:
            assert url == "https://auth.openai.com/oauth/token"
            requests.append(data)
            return _Response(
                200,
                {
                    "access_token": _access_token("acct-login"),
                    "refresh_token": "refresh-login",
                    "expires_in": 3600,
                },
            )

    monkeypatch.setattr("klaude_code.auth.codex.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.httpx.Client", _Client)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.webbrowser.open", lambda url: opened.append(url))

    state = CodexOAuth(CodexTokenManager(auth_file=auth_file)).login(account_name="work")

    assert len(servers) == 1
    assert len(servers[0].requests) == 2
    assert servers[0].closed is True
    assert requests[0]["grant_type"] == "authorization_code"
    assert requests[0]["code"] == "auth-code"
    assert requests[0]["code_verifier"]
    assert state.name == "work"
    assert state.account_id == "acct-login"
    assert CodexTokenManager(auth_file=auth_file).get_state() is not None


def test_login_rejects_state_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        return _CallbackServer(lambda: "other-state", 1)

    monkeypatch.setattr("klaude_code.auth.codex.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.webbrowser.open", lambda _url: True)

    with pytest.raises(CodexOAuthError, match="state mismatch"):
        CodexOAuth(CodexTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()


def test_login_reports_missing_code_when_wait_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    servers: list[_CallbackServer] = []

    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        server = _CallbackServer(lambda: None, None)  # the redirect never arrives
        servers.append(server)
        return server

    clock = iter([0.0, 0.0, 400.0])
    monkeypatch.setattr("klaude_code.auth.codex.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.codex.oauth.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("klaude_code.auth.codex.oauth.webbrowser.open", lambda _url: True)

    with pytest.raises(CodexOAuthError, match="No authorization code received"):
        CodexOAuth(CodexTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()

    assert servers[0].requests == ["request"]
    assert servers[0].closed is True


def test_silent_peer_cannot_stall_the_callback_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent peer must hit a per-connection read deadline, not block the accept loop."""
    # The deadline has to live on the handler: server.timeout only bounds the accept.
    assert OAuthCallbackHandler.timeout is not None
    monkeypatch.setattr(OAuthCallbackHandler, "timeout", 0.2)  # keep the test fast
    server = HTTPServer(("localhost", 0), OAuthCallbackHandler)
    silent_peer = socket.create_connection(cast(tuple[str, int], server.server_address))
    handled = Thread(target=server.handle_request)
    started = time.monotonic()
    try:
        handled.start()
        handled.join(10)
        elapsed = time.monotonic() - started
    finally:
        silent_peer.close()
        server.server_close()

    assert not handled.is_alive()
    assert elapsed < 5


def test_post_token_request_retries_connection_that_never_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[dict[str, str]] = []
    timeouts: list[httpx.Timeout] = []
    results: list[Any] = [
        httpx.ConnectTimeout("handshake timed out"),
        httpx.ConnectError("connection refused"),
        _Response(200, {"ok": True}),
    ]

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            timeouts.append(kwargs["timeout"])

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            attempts.append(data)
            result = results.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

    monkeypatch.setattr("klaude_code.auth.codex.oauth.httpx.Client", _Client)

    response = post_token_request({"grant_type": "refresh_token"})

    assert response.status_code == 200
    assert len(attempts) == len(TOKEN_REQUEST_CONNECT_TIMEOUTS)
    assert [timeout.connect for timeout in timeouts] == list(TOKEN_REQUEST_CONNECT_TIMEOUTS)


def test_post_token_request_gives_up_after_its_attempt_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[dict[str, str]] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            attempts.append(data)
            raise httpx.ConnectTimeout("handshake timed out")

    monkeypatch.setattr("klaude_code.auth.codex.oauth.httpx.Client", _Client)

    with pytest.raises(httpx.ConnectTimeout):
        post_token_request({"grant_type": "authorization_code"})

    assert len(attempts) == len(TOKEN_REQUEST_CONNECT_TIMEOUTS)


def test_post_token_request_does_not_retry_read_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts: list[dict[str, str]] = []

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            attempts.append(data)
            raise httpx.ReadTimeout("no response")

    monkeypatch.setattr("klaude_code.auth.codex.oauth.httpx.Client", _Client)

    with pytest.raises(httpx.ReadTimeout):
        post_token_request({"grant_type": "authorization_code"})

    assert len(attempts) == 1
