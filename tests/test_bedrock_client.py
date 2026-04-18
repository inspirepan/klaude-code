import pytest

from klaude_code.const import ANTHROPIC_BETA_CONTEXT_MANAGEMENT
from klaude_code.llm.anthropic.client import build_payload
from klaude_code.llm.bedrock_anthropic.client import BedrockClient
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


def test_bedrock_payload_inherits_context_management_for_thinking_models() -> None:
    # Bedrock reuses build_payload, so Opus 4.7 via Bedrock should get the same
    # context-management beta + clear_thinking config as the first-party client.
    param = llm_param.LLMCallParameter(
        input=[message.UserMessage(parts=[message.TextPart(text="hi")])],
        model_id="anthropic.claude-opus-4-7-20260215-v1:0",
        thinking=llm_param.Thinking(type="adaptive"),
    )

    payload = build_payload(param)

    assert ANTHROPIC_BETA_CONTEXT_MANAGEMENT in payload.get("betas", [])
    assert payload.get("context_management") == {
        "edits": [{"type": "clear_thinking_20251015", "keep": "all"}],
    }
