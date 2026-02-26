from klaude_code.protocol.llm_param import LLMConfigModelParameter, OpenRouterProviderRouting, Thinking
from klaude_code.ui.common import format_model_params


def test_format_model_params_includes_reasoning_and_provider_routing() -> None:
    params = LLMConfigModelParameter(
        thinking=Thinking(reasoning_effort="medium", reasoning_summary="concise"),
        provider_routing=OpenRouterProviderRouting(sort="throughput", only=["fireworks", "novita"]),
    )
    out = format_model_params(params)

    assert "reasoning medium" in out
    assert "summary concise" in out
    assert "provider routing throughput · fireworks > novita" in out
