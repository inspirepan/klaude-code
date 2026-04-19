from __future__ import annotations

import asyncio
import warnings
from types import SimpleNamespace
from typing import Any

import pytest

from klaude_code.const import LLM_HTTP_TIMEOUT_TOTAL
from klaude_code.llm.google.client import GoogleClient, GoogleStreamStateManager, parse_google_stream
from klaude_code.llm.usage import MetadataTracker
from klaude_code.protocol import llm_param, message


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


def test_parse_google_stream_ignores_unknown_finish_reason_warning() -> None:
    class _FakeChunk:
        def __init__(self) -> None:
            self.response_id = "resp_123"
            self.model_version = None
            self.usage_metadata = None
            self.candidates = [
                SimpleNamespace(
                    finish_reason=SimpleNamespace(name="MALFORMED_RESPONSE"),
                    content=None,
                )
            ]

        def model_dump(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            return {"candidates": [{"finish_reason": "MALFORMED_RESPONSE"}]}

    class _WarningStream:
        def __init__(self) -> None:
            self._sent = False

        def __aiter__(self) -> _WarningStream:
            return self

        async def __anext__(self) -> Any:
            if self._sent:
                raise StopAsyncIteration
            self._sent = True
            warnings.warn("MALFORMED_RESPONSE is not a valid FinishReason", UserWarning, stacklevel=1)
            return _FakeChunk()

    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hello")])],
        session_id=None,
    )
    metadata_tracker = MetadataTracker()
    state = GoogleStreamStateManager(param_model="gemini-2.5-flash")

    async def _collect_items() -> list[message.LLMStreamItem]:
        return [
            item
            async for item in parse_google_stream(
                _WarningStream(),
                param=param,
                metadata_tracker=metadata_tracker,
                state=state,
            )
        ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        items = asyncio.run(_collect_items())

    assert not [w for w in caught if "not a valid FinishReason" in str(w.message)]
    assert len(items) == 1
    assert isinstance(items[0], message.AssistantMessage)
    assert items[0].stop_reason == "error"
