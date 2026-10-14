from klaude_code.protocol.model_id import (
    is_gemini3_model,
    is_gemini3_plus_model,
    is_gemini4_model,
    is_gpt5_model,
    is_gpt5_plus_model,
    is_gpt6_model,
    supports_google_thinking,
    supports_prompt_cache_options_ttl,
)


def test_gemini_generation_helpers_and_thinking() -> None:
    for model_id in ("gemini-4-argon", "google/gemini-4-argon", "GEMINI-4-ARGON:high"):
        assert is_gemini4_model(model_id)
        assert is_gemini3_plus_model(model_id)
        assert supports_google_thinking(model_id)
        assert not is_gemini3_model(model_id)
    assert is_gemini3_plus_model("gemini-3.8-flash")
    assert not is_gemini4_model("gemini-3.8-flash")
    assert supports_google_thinking("gemini-2.5-pro")
    for model_id in (None, "gemini-2.5-pro", "gpt-6-sol"):
        assert not is_gemini3_plus_model(model_id)


def test_gpt5_plus_covers_every_gpt_reasoning_generation() -> None:
    # The apply_patch tool set, the GPT system prompt and the Responses-style
    # reasoning summaries all key off this helper, so a new generation that is
    # missing here silently falls back to the non-GPT behaviour.
    assert is_gpt5_plus_model("gpt-5.6-sol")
    assert is_gpt5_plus_model("gpt-6-astra")
    assert is_gpt5_plus_model("gpt-6-astra:max")
    assert is_gpt5_plus_model("openai/gpt-6-astra")
    assert is_gpt5_plus_model("gpt-6.1-sol")
    assert is_gpt5_plus_model("gpt-6-luna")


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
    assert supports_prompt_cache_options_ttl("gpt-6.1-sol")
    assert supports_prompt_cache_options_ttl("gpt-6-luna")
    assert supports_prompt_cache_options_ttl("gpt-5.6-sol")
    assert not supports_prompt_cache_options_ttl("gpt-5.5")
