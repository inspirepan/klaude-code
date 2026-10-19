from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar

import pytest

from klaude_code.app import auth_flow
from klaude_code.auth import base as auth_base
from klaude_code.auth.chatgpt.token_manager import ChatGPTAuthState
from klaude_code.auth.xai.oauth import XaiDeviceCode
from klaude_code.auth.xai.token_manager import XaiAuthState

CREDENTIAL = ChatGPTAuthState(
    access_token="access",
    refresh_token="refresh",
    expires_at=4102444800,
    client_id="oaiapp_test",
    scopes=["chatgpt.tokens.use.direct"],
)


class _FakeChatGPTTokenManager:
    state: ClassVar[ChatGPTAuthState | None] = CREDENTIAL
    deleted: ClassVar[list[bool]] = []

    def __init__(self, auth_file: Any = None):
        del auth_file

    def is_logged_in(self) -> bool:
        return self.state is not None

    def get_state(self) -> ChatGPTAuthState | None:
        return self.state

    def delete(self) -> None:
        self.deleted.append(True)


def test_execute_chatgpt_login_starts_when_not_logged_in(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls: list[bool] = []

    class _FakeChatGPTOAuth:
        def __init__(self, token_manager: _FakeChatGPTTokenManager):
            del token_manager

        def login(self) -> ChatGPTAuthState:
            login_calls.append(True)
            return CREDENTIAL

    _FakeChatGPTTokenManager.state = None
    monkeypatch.setattr("klaude_code.auth.chatgpt.token_manager.ChatGPTTokenManager", _FakeChatGPTTokenManager)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.ChatGPTOAuth", _FakeChatGPTOAuth)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    assert auth_flow.execute_login("chatgpt") is True
    assert login_calls == [True]


def test_execute_chatgpt_login_relogins_when_confirmed(monkeypatch: pytest.MonkeyPatch) -> None:
    login_calls: list[bool] = []

    class _FakeChatGPTOAuth:
        def __init__(self, token_manager: _FakeChatGPTTokenManager):
            del token_manager

        def login(self) -> ChatGPTAuthState:
            login_calls.append(True)
            return CREDENTIAL

    _FakeChatGPTTokenManager.state = CREDENTIAL
    monkeypatch.setattr("klaude_code.auth.chatgpt.token_manager.ChatGPTTokenManager", _FakeChatGPTTokenManager)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.ChatGPTOAuth", _FakeChatGPTOAuth)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: True)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    assert auth_flow.execute_login("chatgpt") is True
    assert login_calls == [True]


def test_execute_chatgpt_login_decline_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeChatGPTOAuth:
        def __init__(self, token_manager: _FakeChatGPTTokenManager):
            del token_manager

        def login(self) -> ChatGPTAuthState:
            raise AssertionError("OAuth should not start")

    _FakeChatGPTTokenManager.state = CREDENTIAL
    monkeypatch.setattr("klaude_code.auth.chatgpt.token_manager.ChatGPTTokenManager", _FakeChatGPTTokenManager)
    monkeypatch.setattr("klaude_code.auth.chatgpt.oauth.ChatGPTOAuth", _FakeChatGPTOAuth)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: False)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    assert auth_flow.execute_login("chatgpt") is False


def test_execute_chatgpt_logout_deletes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeChatGPTTokenManager.state = CREDENTIAL
    _FakeChatGPTTokenManager.deleted = []
    monkeypatch.setattr("klaude_code.auth.chatgpt.token_manager.ChatGPTTokenManager", _FakeChatGPTTokenManager)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: True)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    auth_flow.execute_logout("chatgpt")

    assert _FakeChatGPTTokenManager.deleted == [True]


def test_execute_xai_login_displays_device_code(monkeypatch: pytest.MonkeyPatch) -> None:
    logs: list[Any] = []

    class _TokenManager:
        def get_state(self) -> None:
            return None

    class _OAuth:
        def __init__(self, _manager: _TokenManager):
            pass

        def login(self, notifier: Any) -> XaiAuthState:
            notifier(
                XaiDeviceCode(
                    device_code="device",
                    user_code="USER-CODE",
                    verification_uri="https://auth.x.ai/verify",
                    verification_uri_complete=None,
                    expires_in=300,
                    interval=5,
                )
            )
            return XaiAuthState(access_token="access", refresh_token="refresh", expires_at=4102444800)

    monkeypatch.setattr("klaude_code.auth.xai.token_manager.XaiTokenManager", _TokenManager)
    monkeypatch.setattr("klaude_code.auth.xai.oauth.XaiOAuth", _OAuth)
    monkeypatch.setattr(auth_flow, "log", lambda message: logs.append(message))

    completed = auth_flow.execute_login("grok-build")

    assert completed is True
    assert "  Verification URL: https://auth.x.ai/verify" in logs
    assert "  User code: USER-CODE" in logs
    assert ("xAI Grok OAuth login successful!", "green") in logs


def test_execute_bedrock_login_decline_all_updates_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("klaude_code.auth.env.KLAUDE_AUTH_FILE", tmp_path / "klaude-auth.json")
    monkeypatch.setenv("AWS_BEDROCK_ACCESS_KEY_ID", "AKIA-EXISTING")
    monkeypatch.setenv("AWS_BEDROCK_SECRET_ACCESS_KEY", "secret-existing")
    monkeypatch.setenv("AWS_BEDROCK_REGION", "us-east-1")
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: False)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    assert auth_flow.execute_login("bedrock") is False


def test_execute_bedrock_login_saves_new_credentials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    monkeypatch.setattr("klaude_code.auth.env.KLAUDE_AUTH_FILE", auth_file)
    for var in ("AWS_BEDROCK_ACCESS_KEY_ID", "AWS_BEDROCK_SECRET_ACCESS_KEY", "AWS_BEDROCK_REGION"):
        monkeypatch.delenv(var, raising=False)
    prompts = iter(["AKIA-NEW", "secret-new", "us-west-2"])
    monkeypatch.setattr(auth_flow.typer, "prompt", lambda _prompt, hide_input=False: next(prompts))
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    assert auth_flow.execute_login("bedrock") is True
    saved = json.loads(auth_file.read_text())
    assert saved["env"]["AWS_BEDROCK_REGION"] == "us-west-2"


def test_execute_xai_logout_deletes_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    deleted: list[bool] = []

    class _TokenManager:
        def is_logged_in(self) -> bool:
            return True

        def delete(self) -> None:
            deleted.append(True)

    monkeypatch.setattr("klaude_code.auth.xai.token_manager.XaiTokenManager", _TokenManager)
    monkeypatch.setattr(auth_flow.typer, "confirm", lambda _prompt: True)
    monkeypatch.setattr(auth_flow, "log", lambda _message: None)

    auth_flow.execute_logout("xai")

    assert deleted == [True]


def test_execute_logout_github_copilot_cleans_legacy_auth_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    auth_file = tmp_path / "klaude-auth.json"
    auth_file.write_text(
        json.dumps(
            {
                "copilot": {"access_token": "legacy"},
                "github-copilot": {"access_token": "current"},
                "env": {"OPENAI_API_KEY": "sk-test"},
            }
        )
    )
    logs: list[Any] = []

    monkeypatch.setattr(auth_base, "KLAUDE_AUTH_FILE", auth_file)
    monkeypatch.setattr(auth_flow, "log", lambda message: logs.append(message))

    auth_flow.execute_logout("github-copilot")

    saved = json.loads(auth_file.read_text())
    assert saved == {"env": {"OPENAI_API_KEY": "sk-test"}}
    assert logs == [("Removed legacy GitHub Copilot auth state.", "green")]
