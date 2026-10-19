from __future__ import annotations

import json
import socket
import time
import uuid
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from klaude_code.auth.chatgpt.exceptions import ChatGPTOAuthError
from klaude_code.auth.chatgpt.oauth import (
    AGENT_NAME_HINT,
    DIRECT_TOKEN_SCOPE,
    DYNAMIC_CLIENT_ID,
    RESOURCE,
    SCOPE,
    TOKEN_REQUEST_CONNECT_TIMEOUTS,
    ChatGPTOAuth,
    OAuthCallbackHandler,
    post_token_request,
)
from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState, ChatGPTTokenManager

TOKEN_URL = "https://auth.openai.com/api/accounts/oauth/token"
ISSUED_CLIENT_ID = "oaiapp_issued"


class _Response:
    def __init__(self, status_code: int, data: dict[str, Any], text: str = ""):
        self.status_code = status_code
        self._data = data
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._data


def _token_response(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "access_token": "access-login",
        "refresh_token": "refresh-login",
        "expires_in": 3600,
        "id_token": "id-token",
        "scope": SCOPE,
    }
    data.update(overrides)
    return data


class _CallbackServer:
    """Stand in for the local HTTP server the browser is redirected to."""

    def __init__(self, state_of: Any, resolve_after: int | None, client_id: str | None = ISSUED_CLIENT_ID) -> None:
        self.state_of = state_of
        self.resolve_after = resolve_after
        self.client_id = client_id
        self.requests: list[str] = []
        self.timeout: float | None = None
        self.closed = False

    def handle_request(self) -> None:
        self.requests.append("request")
        if self.resolve_after is None or len(self.requests) < self.resolve_after:
            return
        OAuthCallbackHandler.code = "auth-code"
        OAuthCallbackHandler.state = self.state_of()
        OAuthCallbackHandler.client_id = self.client_id
        OAuthCallbackHandler.scope = SCOPE
        OAuthCallbackHandler.resolved = True

    def server_close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def _reset_callback_handler() -> None:
    OAuthCallbackHandler.code = None
    OAuthCallbackHandler.state = None
    OAuthCallbackHandler.client_id = None
    OAuthCallbackHandler.scope = None
    OAuthCallbackHandler.error = None
    OAuthCallbackHandler.resolved = False


def test_login_registers_client_then_exchanges_and_saves(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
            assert url == TOKEN_URL
            requests.append(data)
            return _Response(200, _token_response())

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.webbrowser.open", lambda url: opened.append(url))

    state = ChatGPTOAuth(ChatGPTTokenManager(auth_file=auth_file)).login()

    authorize = urlparse(opened[0])
    params = parse_qs(authorize.query)
    device_id = json.loads(auth_file.read_text())["chatgpt_device_id"]
    uuid.UUID(device_id)

    assert authorize.scheme == "https"
    assert authorize.netloc == "auth.openai.com"
    assert authorize.path == "/api/accounts/authorize"
    assert params["client_id"] == [DYNAMIC_CLIENT_ID]
    assert params["agent_name_hint"] == [AGENT_NAME_HINT]
    assert params["ext_agent_host_id"] == [f"urn:uuid:{device_id}"]
    assert params["resource"] == [RESOURCE]
    assert params["scope"] == [SCOPE]
    assert params["code_challenge_method"] == ["S256"]
    assert params["nonce"]

    assert len(servers) == 1
    assert len(servers[0].requests) == 2
    assert servers[0].closed is True
    assert requests[0]["grant_type"] == "authorization_code"
    assert requests[0]["client_id"] == ISSUED_CLIENT_ID
    assert requests[0]["code"] == "auth-code"
    assert requests[0]["code_verifier"]
    assert requests[0]["resource"] == RESOURCE

    assert state.client_id == ISSUED_CLIENT_ID
    assert state.scopes == SCOPE.split()
    assert state.id_token == "id-token"
    assert DIRECT_TOKEN_SCOPE in state.scopes

    stored = ChatGPTTokenManager(auth_file=auth_file).get_state()
    assert stored is not None
    assert stored.client_id == ISSUED_CLIENT_ID


def test_login_rejects_state_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        return _CallbackServer(lambda: "other-state", 1)

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.webbrowser.open", lambda _url: True)

    with pytest.raises(ChatGPTOAuthError, match="state mismatch"):
        ChatGPTOAuth(ChatGPTTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()


def test_login_rejects_callback_without_issued_client_id(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs

        def state_of() -> str:
            return parse_qs(urlparse(opened[0]).query)["state"][0]

        return _CallbackServer(state_of, 1, client_id=None)

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.webbrowser.open", lambda url: opened.append(url))

    with pytest.raises(ChatGPTOAuthError, match="did not return a client ID"):
        ChatGPTOAuth(ChatGPTTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()


def test_token_response_requires_direct_usage_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        return _CallbackServer(lambda: parse_qs(urlparse(opened[0]).query)["state"][0], 1)

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, _url: str, *, data: dict[str, str]) -> _Response:
            del data
            return _Response(200, _token_response(scope="openid profile email"))

    opened: list[str] = []
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.webbrowser.open", lambda url: opened.append(url))

    with pytest.raises(ChatGPTOAuthError, match=DIRECT_TOKEN_SCOPE):
        ChatGPTOAuth(ChatGPTTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()


def test_refresh_uses_issued_client_id_and_resource(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, str]] = []
    auth_file = tmp_path / "klaude-auth.json"
    manager = ChatGPTTokenManager(auth_file=auth_file)
    manager.save(
        ChatGPTAuthState(
            access_token="old-access",
            refresh_token="old-refresh",
            expires_at=0,
            client_id=ISSUED_CLIENT_ID,
            scopes=[str(part) for part in SCOPE.split()],
        )
    )

    class _Client:
        def __init__(self, **kwargs: Any) -> None:
            pass

        def __enter__(self) -> _Client:
            return self

        def __exit__(self, *args: Any) -> None:
            return None

        def post(self, url: str, *, data: dict[str, str]) -> _Response:
            assert url == TOKEN_URL
            requests.append(data)
            return _Response(
                200,
                _token_response(
                    access_token="new-access",
                    scope=SCOPE,
                ),
            )

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

    state = ChatGPTOAuth(manager).refresh()

    assert requests == [
        {
            "grant_type": "refresh_token",
            "client_id": ISSUED_CLIENT_ID,
            "refresh_token": "old-refresh",
            "resource": RESOURCE,
        }
    ]
    assert state.access_token == "new-access"
    assert state.client_id == ISSUED_CLIENT_ID


def test_login_reports_missing_code_when_wait_expires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    servers: list[_CallbackServer] = []

    def _create_server(address: Any, handler: Any, **kwargs: Any) -> _CallbackServer:
        del address, handler, kwargs
        server = _CallbackServer(lambda: None, None)  # the redirect never arrives
        servers.append(server)
        return server

    clock = iter([0.0, 0.0, 400.0])
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.HTTPServer", _create_server)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.time.monotonic", lambda: next(clock))
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.webbrowser.open", lambda _url: True)

    with pytest.raises(ChatGPTOAuthError, match="No authorization code received"):
        ChatGPTOAuth(ChatGPTTokenManager(auth_file=tmp_path / "klaude-auth.json")).login()

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

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

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

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

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

    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.httpx.Client", _Client)

    with pytest.raises(httpx.ReadTimeout):
        post_token_request({"grant_type": "authorization_code"})

    assert len(attempts) == 1
