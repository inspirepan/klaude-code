from klaude_code.protocol.model_id import (
    is_gpt5_model,
    is_gpt5_plus_model,
    is_gpt6_model,
    supports_prompt_cache_options_ttl,
)


def test_gpt5_plus_covers_every_gpt_reasoning_generation() -> None:
    # The apply_patch tool set, the GPT system prompt and the Responses-style
    # reasoning summaries all key off this helper, so a new generation that is
    # missing here silently falls back to the non-GPT behaviour.
    assert is_gpt5_plus_model("gpt-5.6-sol")
    assert is_gpt5_plus_model("gpt-6-astra")
    assert is_gpt5_plus_model("gpt-6-astra:max")
    assert is_gpt5_plus_model("openai/gpt-6-astra")


def test_gpt5_plus_excludes_older_and_unrelated_models() -> None:
    assert not is_gpt5_plus_model("gpt-4.1")
    assert not is_gpt5_plus_model("sonnet")
    assert not is_gpt5_plus_model(None)


def test_generation_helpers_stay_specific() -> None:
    assert is_gpt5_model("gpt-5.6-sol")
    assert not is_gpt5_model("gpt-6-astra")
    assert is_gpt6_model("gpt-6-astra")
    assert not is_gpt6_model("gpt-5.6-sol")


def test_prompt_cache_ttl_covers_gpt56_and_newer() -> None:
    assert supports_prompt_cache_options_ttl("gpt-6-astra")
    assert supports_prompt_cache_options_ttl("gpt-5.6-sol")
    assert not supports_prompt_cache_options_ttl("gpt-5.5")
