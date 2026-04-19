from typing import Any, ClassVar

import pytest

from klaude_code.const import ANTHROPIC_BETA_CONTEXT_MANAGEMENT, CLAUDE_CODE_IDENTITY
from klaude_code.llm.bedrock_anthropic import client as bedrock_client_module
from klaude_code.llm.bedrock_anthropic.client import BedrockClient, build_bedrock_request
from klaude_code.protocol import llm_param, message


def test_bedrock_client_reports_missing_optional_dependencies(monkeypatch: pytest.MonkeyPatch) -> None:
    import klaude_code.llm.bedrock_anthropic.client as bedrock_client_module

    real_find_spec = bedrock_client_module.find_spec

    def _find_spec(name: str):
        if name in {"boto3", "botocore"}:
            return None
        return real_find_spec(name)

    monkeypatch.setattr(bedrock_client_module, "find_spec", _find_spec)

    config = llm_param.LLMConfigParameter(
        provider_name="bedrock-test",
        protocol=llm_param.LLMClientProtocol.BEDROCK,
        aws_access_key="test-access-key",
        aws_secret_key="test-secret-key",
        aws_region="us-east-1",
        model_id="anthropic.claude-sonnet-4-6",
    )

    with pytest.raises(ModuleNotFoundError, match="Bedrock support requires boto3 and botocore"):
        BedrockClient.create(config)

def test_bedrock_request_uses_converse_fields_for_opus_47() -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id="global.anthropic.claude-opus-4-7",
        thinking=llm_param.Thinking(type="adaptive"),
        effort="xhigh",
        max_tokens=64000,
        temperature=0.2,
    )

    request = build_bedrock_request(param, region="us-east-1")

    assert request["modelId"] == "global.anthropic.claude-opus-4-7"
    assert request["inferenceConfig"] == {
        "maxTokens": 64000,
    }
    assert request["additionalModelRequestFields"] == {
        "thinking": {"type": "adaptive", "display": "summarized"},
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        "anthropic_beta": [ANTHROPIC_BETA_CONTEXT_MANAGEMENT],
        "output_config": {"effort": "xhigh"},
    }
    assert request["system"][:2] == [
        {"text": CLAUDE_CODE_IDENTITY},
        {"cachePoint": {"type": "default"}},
    ]
    assert "context_management" not in request

def test_bedrock_request_keeps_non_opus47_temperature_and_interleaved_beta() -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id="global.anthropic.claude-sonnet-4-5-20250929-v1:0",
        thinking=llm_param.Thinking(type="enabled", budget_tokens=4096),
        temperature=0.3,
    )

    request = build_bedrock_request(param, region="us-east-1")

    assert request["inferenceConfig"] == {
        "maxTokens": 32000,
        "temperature": 0.3,
    }
    assert request["additionalModelRequestFields"] == {
        "thinking": {"type": "enabled", "budget_tokens": 4096, "display": "summarized"},
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        "anthropic_beta": [
            ANTHROPIC_BETA_CONTEXT_MANAGEMENT,
            "interleaved-thinking-2025-05-14",
        ],
    }

def test_bedrock_request_keeps_thinking_for_arn_models() -> None:
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id="arn:aws:bedrock:us-east-1:123456789012:inference-profile/my-profile",
        thinking=llm_param.Thinking(type="adaptive"),
        effort="high",
    )

    request = build_bedrock_request(param, region="us-east-1")

    assert request["additionalModelRequestFields"] == {
        "thinking": {"type": "adaptive", "display": "summarized"},
        "context_management": {"edits": [{"type": "clear_thinking_20251015", "keep": "all"}]},
        "anthropic_beta": [ANTHROPIC_BETA_CONTEXT_MANAGEMENT],
        "output_config": {"effort": "high"},
    }

def test_bedrock_request_fetches_remote_image_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        headers: ClassVar[dict[str, str]] = {"content-type": "image/png"}
        content: ClassVar[bytes] = b"png-bytes"

        def raise_for_status(self) -> None:
            return None

    def _fake_get(*args: Any, **kwargs: Any) -> _Response:
        return _Response()

    monkeypatch.setattr(bedrock_client_module.httpx, "get", _fake_get)

    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.ImageURLPart(url="https://example.com/image.png")])],
        model_id="global.anthropic.claude-opus-4-7",
    )

    request = build_bedrock_request(param, region="us-east-1")

    assert request["messages"][0]["content"] == [
        {"image": {"format": "png", "source": {"bytes": b"png-bytes"}}},
    ]
