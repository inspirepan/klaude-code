from klaude_code.llm.openai_responses.prompt_cache import build_prompt_cache_payload


def test_prompt_cache_payload_uses_ttl_for_gpt56() -> None:
    assert build_prompt_cache_payload("gpt-5.6-sol", None) == {"prompt_cache_options": {"ttl": "30m"}}


def test_prompt_cache_payload_uses_retention_for_older_gpt() -> None:
    assert build_prompt_cache_payload("gpt-5.5", None) == {"prompt_cache_retention": "24h"}


def test_prompt_cache_payload_respects_short_retention() -> None:
    assert build_prompt_cache_payload("gpt-5.6-sol", "short") == {}


def test_prompt_cache_payload_uses_long_retention_for_unknown_model() -> None:
    assert build_prompt_cache_payload("custom-model", "long") == {"prompt_cache_retention": "24h"}
