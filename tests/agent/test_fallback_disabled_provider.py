"""Call-time provider disable checks in FallbackLLMClient.

Disabling a provider via /manage-providers must reach sessions that are
already running: the next call() on a candidate whose provider is disabled
returns a fallbackable error stream, so the task loop advances the chain
and retries instead of silently keeping the disabled provider.
"""

import asyncio
from collections.abc import Coroutine
from typing import Any

import pytest

import klaude_code.agent.runtime.llm as runtime_llm
from klaude_code.agent.model_fallback import is_fallbackable_llm_error
from klaude_code.agent.runtime.llm import FallbackLLMClient
from klaude_code.config.config import Config, ModelConfig, ModelConfigCandidate, ProviderConfig
from klaude_code.llm.client import LLMClientABC, LLMStreamABC
from klaude_code.protocol import llm_param, message


def _run[T](coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


def _make_client() -> FallbackLLMClient:
    return FallbackLLMClient(
        [
            ModelConfigCandidate(
                selector="model-a@provider-a",
                model_name="model-a",
                provider="provider-a",
                llm_config=llm_param.LLMConfigParameter(
                    provider_name="provider-a",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    model_id="model-a",
                ),
            ),
            ModelConfigCandidate(
                selector="model-b@provider-b",
                model_name="model-b",
                provider="provider-b",
                llm_config=llm_param.LLMConfigParameter(
                    provider_name="provider-b",
                    protocol=llm_param.LLMClientProtocol.OPENAI,
                    model_id="model-b",
                ),
            ),
        ]
    )


def _make_config(*, disable_provider_a: bool) -> Config:
    def _provider(name: str, model: str, disabled: bool) -> ProviderConfig:
        return ProviderConfig(
            provider_name=name,
            protocol=llm_param.LLMClientProtocol.OPENAI,
            api_key="test-api-key",
            base_url="https://api.example.com/v1",
            disabled=disabled,
            model_list=[ModelConfig(model_name=model, model_id=model)],
        )

    return Config(
        provider_list=[
            _provider("provider-a", "model-a", disable_provider_a),
            _provider("provider-b", "model-b", False),
        ],
        main_model="model-a",
    )


async def _collect_stream_error(stream: LLMStreamABC) -> str | None:
    async for item in stream:
        if isinstance(item, message.StreamErrorItem):
            return item.error
    return None


class _SentinelStream(LLMStreamABC):
    def __aiter__(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        raise NotImplementedError

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


class _SentinelClient(LLMClientABC):
    @classmethod
    def create(cls, config: llm_param.LLMConfigParameter) -> LLMClientABC:
        return cls(config)

    async def call(self, param: llm_param.LLMCallParameter) -> LLMStreamABC:
        del param
        return _SentinelStream()


def test_disabled_provider_yields_fallbackable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_llm, "load_config", lambda: _make_config(disable_provider_a=True))
    client = _make_client()

    async def _scenario() -> str | None:
        return await _collect_stream_error(await client.call(llm_param.LLMCallParameter(input=[])))

    error = _run(_scenario())

    assert error is not None
    assert "model-a@provider-a" in error
    assert "provider 'provider-a' is disabled" in error
    # The task loop only advances the chain for fallbackable errors.
    assert is_fallbackable_llm_error(error)


def test_next_candidate_serves_after_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_llm, "load_config", lambda: _make_config(disable_provider_a=True))
    monkeypatch.setattr(runtime_llm, "create_llm_client", _SentinelClient.create)
    client = _make_client()

    async def _scenario() -> LLMStreamABC:
        error = await _collect_stream_error(await client.call(llm_param.LLMCallParameter(input=[])))
        assert error is not None
        assert client.fallback_to_next() is not None
        return await client.call(llm_param.LLMCallParameter(input=[]))

    assert isinstance(_run(_scenario()), _SentinelStream)


def test_enabled_provider_not_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runtime_llm, "load_config", lambda: _make_config(disable_provider_a=False))
    monkeypatch.setattr(runtime_llm, "create_llm_client", _SentinelClient.create)
    client = _make_client()

    stream = _run(client.call(llm_param.LLMCallParameter(input=[])))
    assert isinstance(stream, _SentinelStream)


def test_unreadable_config_does_not_block(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise() -> Config:
        raise ValueError("broken config")

    monkeypatch.setattr(runtime_llm, "load_config", _raise)
    monkeypatch.setattr(runtime_llm, "create_llm_client", _SentinelClient.create)
    client = _make_client()

    stream = _run(client.call(llm_param.LLMCallParameter(input=[])))
    assert isinstance(stream, _SentinelStream)
