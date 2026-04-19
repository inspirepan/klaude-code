from __future__ import annotations

from typing import Any

import pytest

from klaude_code.const import LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.google_vertex.client import GoogleVertexClient
from klaude_code.protocol import llm_param


def test_google_vertex_client_loads_credentials_with_cloud_platform_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}
    fake_credentials = object()

    def _fake_load_credentials_from_file(path: str, scopes: list[str] | None = None) -> tuple[object, None]:
        captured["path"] = path
        captured["scopes"] = scopes
        return fake_credentials, None

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

    monkeypatch.setattr(
        "klaude_code.llm.google_vertex.client.load_credentials_from_file",
        _fake_load_credentials_from_file,
    )
    monkeypatch.setattr("klaude_code.llm.google_vertex.client.Client", _FakeClient)

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE_VERTEX,
        google_application_credentials="/tmp/service-account.json",
        google_cloud_project="my-project",
        google_cloud_location="global",
    )

    _ = GoogleVertexClient(config)

    assert captured["path"] == "/tmp/service-account.json"
    assert captured["scopes"] == ["https://www.googleapis.com/auth/cloud-platform"]
    assert captured["client_kwargs"]["vertexai"] is True
    assert captured["client_kwargs"]["credentials"] is fake_credentials
    assert captured["client_kwargs"]["project"] == "my-project"
    assert captured["client_kwargs"]["location"] == "global"
    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.timeout == int(LLM_HTTP_TIMEOUT_TOTAL * 1000)


def test_google_vertex_client_sets_timeout_when_custom_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            captured["client_kwargs"] = kwargs

    monkeypatch.setattr("klaude_code.llm.google_vertex.client.Client", _FakeClient)

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.GOOGLE_VERTEX,
        base_url="https://vertex.example.com",
    )

    _ = GoogleVertexClient(config)

    http_options = captured["client_kwargs"]["http_options"]
    assert http_options.base_url == "https://vertex.example.com"
    assert http_options.api_version == ""
    assert http_options.timeout == int(LLM_HTTP_TIMEOUT_TOTAL * 1000)
