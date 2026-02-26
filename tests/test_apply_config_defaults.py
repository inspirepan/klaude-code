from klaude_code.llm.input_common import apply_config_defaults
from klaude_code.protocol import llm_param, message


def _dummy_history() -> list[message.Message]:
    return [message.UserMessage(parts=[message.TextPart(text="hi")])]


def test_apply_config_defaults_applies_missing_fields() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.OPENROUTER,
        model_id="openai/gpt-5.3-codex",
        temperature=0.2,
        max_tokens=4096,
        context_limit=200000,
        verbosity="high",
        thinking=llm_param.Thinking(reasoning_effort="high"),
        provider_routing=llm_param.OpenRouterProviderRouting(sort="latency"),
    )
    param = llm_param.LLMCallParameter(input=_dummy_history())

    param = apply_config_defaults(param, config)

    assert param.model_id == "openai/gpt-5.3-codex"
    assert param.temperature == 0.2
    assert param.max_tokens == 4096
    assert param.context_limit == 200000
    assert param.verbosity == "high"
    assert param.thinking is not None and param.thinking.reasoning_effort == "high"
    assert param.provider_routing is not None and param.provider_routing.sort == "latency"


def test_apply_config_defaults_does_not_override_existing_fields() -> None:
    config = llm_param.LLMConfigParameter(
        protocol=llm_param.LLMClientProtocol.OPENROUTER,
        model_id="openai/gpt-5.3-codex",
        temperature=0.2,
        max_tokens=4096,
        context_limit=200000,
        verbosity="high",
        thinking=llm_param.Thinking(reasoning_effort="high"),
        provider_routing=llm_param.OpenRouterProviderRouting(sort="latency"),
    )
    param = llm_param.LLMCallParameter(
        input=_dummy_history(),
        model_id="openai/gpt-5.2",
        temperature=0.9,
        max_tokens=1024,
        context_limit=100000,
        verbosity="low",
        thinking=llm_param.Thinking(reasoning_effort="minimal"),
        provider_routing=llm_param.OpenRouterProviderRouting(sort="throughput"),
    )

    param = apply_config_defaults(param, config)

    assert param.model_id == "openai/gpt-5.2"
    assert param.temperature == 0.9
    assert param.max_tokens == 1024
    assert param.context_limit == 100000
    assert param.verbosity == "low"
    assert param.thinking is not None and param.thinking.reasoning_effort == "minimal"
    assert param.provider_routing is not None and param.provider_routing.sort == "throughput"
