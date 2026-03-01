from __future__ import annotations

from typing import Any

import pytest

from klaude_code.const import LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.google.client import GoogleClient
from klaude_code.protocol import llm_param


def test_google_client_sets_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

    monkeypatch.setattr("klaude_code.llm.google.client.Client", _FakeClient)

    config = llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.GOOGLE)

    _ = GoogleClient(config)

    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.timeout == int(LLM_HTTP_TIMEOUT_TOTAL * 1000)


def test_google_client_sets_timeout_when_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

    monkeypatch.setattr("klaude_code.llm.google.client.Client", _FakeClient)

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE,
        base_url="https://gemini.example.com",
    )

    _ = GoogleClient(config)

    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.base_url == "https://gemini.example.com"
    assert http_options.api_version == ""
    assert http_options.timeout == int(LLM_HTTP_TIMEOUT_TOTAL * 1000)
