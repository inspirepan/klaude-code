"""Characterization tests for the httpx.Timeout values each LLM client builds.

These lock in the resolved total / connect / read timeout values currently
constructed per provider so a future create_http_timeout factory can be proven
behavior-preserving. They assert what IS, not what SHOULD be.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from klaude_code.const import (
    LLM_HTTP_TIMEOUT_CONNECT,
    LLM_HTTP_TIMEOUT_READ,
    LLM_HTTP_TIMEOUT_TOTAL,
)
from klaude_code.protocol import llm_param


def test_const_timeout_values_snapshot() -> None:
    # Snapshot the constants that feed every client.
    assert LLM_HTTP_TIMEOUT_TOTAL == 300.0
    assert LLM_HTTP_TIMEOUT_CONNECT == 15.0
    assert LLM_HTTP_TIMEOUT_READ == 285.0


def test_anthropic_client_timeout_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncAnthropic:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

    import klaude_code.llm.anthropic.client as anthropic_client_module

    monkeypatch.setattr(anthropic_client_module.anthropic, "AsyncAnthropic", _FakeAsyncAnthropic)

    config = llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.ANTHROPIC, api_key="k")
    anthropic_client_module.AnthropicClient(config)

    timeout = captured["kwargs"]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    # total -> connect/read overridden; write/pool default to the total value.
    assert timeout.connect == 15.0
    assert timeout.read == 285.0
    assert timeout.write == 300.0
    assert timeout.pool == 300.0


def test_responses_openai_client_timeout_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

    import klaude_code.llm.openai_responses.client as responses_client_module

    monkeypatch.setattr(responses_client_module, "AsyncOpenAI", _FakeAsyncOpenAI)

    config = llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.RESPONSES, api_key="k")
    responses_client_module.ResponsesClient(config)

    timeout = captured["kwargs"]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 15.0
    assert timeout.read == 285.0
    assert timeout.write == 300.0
    assert timeout.pool == 300.0


def test_responses_azure_client_timeout_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

    import klaude_code.llm.openai_responses.client as responses_client_module

    monkeypatch.setattr(responses_client_module, "AsyncAzureOpenAI", _FakeAsyncAzureOpenAI)

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.RESPONSES,
        api_key="k",
        base_url="https://example.openai.azure.com",
        is_azure=True,
        azure_api_version="2024-10-01",
    )
    responses_client_module.ResponsesClient(config)

    timeout = captured["kwargs"]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 15.0
    assert timeout.read == 285.0


def test_bedrock_converse_client_uses_botocore_config_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bedrock ConverseStream uses a different timeout shape: botocore Config
    connect_timeout / read_timeout (NO total), not an httpx.Timeout."""
    import klaude_code.llm.bedrock_anthropic.client as bedrock_client_module

    captured: dict[str, Any] = {}

    class _FakeConfig:
        def __init__(self, **kwargs: Any) -> None:
            captured["config_kwargs"] = kwargs

    class _FakeBedrockClient:
        class _Meta:
            class _Events:
                def register(self, *args: Any, **kwargs: Any) -> None:
                    return None

            events = _Events()

        meta = _Meta()

    class _FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            captured["session_kwargs"] = kwargs

        def client(self, *args: Any, **kwargs: Any) -> _FakeBedrockClient:
            captured["client_args"] = args
            captured["client_kwargs"] = kwargs
            return _FakeBedrockClient()

    fake_boto3 = type("_boto3", (), {"Session": _FakeSession})
    fake_botocore_config = type("_botocore_config_mod", (), {"Config": _FakeConfig})

    import sys

    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore_config)
    monkeypatch.setattr(bedrock_client_module, "BEDROCK_USE_CONVERSE_STREAM", True)
    monkeypatch.setattr(bedrock_client_module, "find_spec", lambda name: object())

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.BEDROCK,
        aws_access_key="ak",
        aws_secret_key="sk",
        aws_region="us-east-1",
        model_id="anthropic.claude-sonnet-4-6",
    )
    bedrock_client_module.BedrockClient(config)

    config_kwargs = captured["config_kwargs"]
    assert config_kwargs == {
        "connect_timeout": 15.0,
        "read_timeout": 285.0,
    }
    # No "total" concept exists in botocore Config; this is the distinct shape.
    assert "timeout" not in config_kwargs


def test_bedrock_messages_client_uses_httpx_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NOT using ConverseStream, Bedrock routes through AsyncAnthropicBedrock
    with the standard httpx.Timeout shape (total/connect/read)."""
    import klaude_code.llm.bedrock_anthropic.client as bedrock_client_module

    captured: dict[str, Any] = {}

    class _FakeAsyncAnthropicBedrock:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

    import anthropic

    monkeypatch.setattr(anthropic, "AsyncAnthropicBedrock", _FakeAsyncAnthropicBedrock)
    monkeypatch.setattr(bedrock_client_module, "BEDROCK_USE_CONVERSE_STREAM", False)

    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.BEDROCK,
        aws_access_key="ak",
        aws_secret_key="sk",
        aws_region="us-east-1",
        model_id="anthropic.claude-sonnet-4-6",
    )
    bedrock_client_module.BedrockClient(config)

    timeout = captured["kwargs"]["timeout"]
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 15.0
    assert timeout.read == 285.0
    assert timeout.write == 300.0
    assert timeout.pool == 300.0
