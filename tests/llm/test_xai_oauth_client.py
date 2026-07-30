from __future__ import annotations

from typing import Any

import pytest

from klaude_code.auth.xai.token_manager import XaiAuthState
from klaude_code.llm.xai_oauth import client as xai_client
from klaude_code.protocol import llm_param, message


class _TokenManager:
    def is_logged_in(self) -> bool:
        return True

    def get_state(self) -> XaiAuthState:
        return XaiAuthState(access_token="oauth-token", refresh_token="refresh", expires_at=4102444800)


def _config(base_url: str | None = None) -> llm_param.LLMConfigParameter:
    return llm_param.LLMConfigParameter(
        provider_name="xai",
        protocol=llm_param.LLMClientProtocol.XAI_OAUTH,
        base_url=base_url,
        model_id="grok-build-0.1",
    )


def test_xai_client_uses_official_endpoint_and_oauth_token(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def create_client(**kwargs: Any) -> object:
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(xai_client, "XaiTokenManager", _TokenManager)
    monkeypatch.setattr(xai_client, "AsyncOpenAI", create_client)

    client = xai_client.XaiOAuthClient(_config())

    assert client.protocol == llm_param.LLMClientProtocol.XAI_OAUTH
    assert captured["api_key"] == "oauth-token"
    assert captured["base_url"] == xai_client.XAI_BASE_URL
    assert captured["default_headers"] == {"User-Agent": "klaude-code/2"}


def test_xai_client_rejects_custom_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(xai_client, "XaiTokenManager", _TokenManager)

    with pytest.raises(ValueError, match="only supports the official"):
        xai_client.XaiOAuthClient(_config("https://example.com/v1"))


@pytest.mark.parametrize(
    ("model_id", "expects_reasoning"),
    [("grok-build-0.1", False), ("grok-4.5", True)],
)
def test_xai_payload_omits_reasoning_controls_only_for_grok_build(
    model_id: str,
    expects_reasoning: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(xai_client, "XaiTokenManager", _TokenManager)
    monkeypatch.setattr(xai_client, "AsyncOpenAI", lambda **_kwargs: object())
    client = xai_client.XaiOAuthClient(_config())
    param = llm_param.LLMCallParameter(
        model_id=model_id,
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        thinking=llm_param.Thinking(reasoning_effort="high"),
        max_tokens=1024,
    )

    payload = client._build_payload(param)

    assert ("reasoning" in payload) is expects_reasoning
    assert ("include" in payload) is expects_reasoning
