from types import SimpleNamespace
from typing import Any

import pytest

from klaude_code.llm.openrouter.client import OpenRouterClient, build_payload
from klaude_code.protocol import llm_param, message


def test_openrouter_client_sets_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _FakeAsyncOpenAI:
        def __init__(self, **kwargs: Any) -> None:
            captured["kwargs"] = kwargs

    monkeypatch.setattr(
        "klaude_code.llm.openrouter.client.openai",
        SimpleNamespace(AsyncOpenAI=_FakeAsyncOpenAI),
    )

    config = llm_param.LLMConfigParameter(protocol=llm_param.LLMClientProtocol.OPENROUTER)

    _ = OpenRouterClient(config)

    assert captured["kwargs"]["default_headers"] == {"User-Agent": "klaude-code/2"}


@pytest.mark.parametrize(
    "model_id",
    ["anthropic/claude-opus-4.7", "anthropic/claude-opus-4.8", "anthropic/claude-opus-5"],
)
def test_build_payload_omits_temperature_for_new_opus_models(model_id: str) -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id=model_id,
        temperature=0.2,
    )

    payload, _, _ = build_payload(param)

    assert "temperature" not in payload
