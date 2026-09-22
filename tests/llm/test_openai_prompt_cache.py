from klaude_code.llm.openai_codex.client import build_payload as build_codex_payload
from klaude_code.llm.openai_responses.client import build_payload as build_responses_payload
from klaude_code.llm.openai_responses.prompt_cache import build_prompt_cache_payload
from klaude_code.protocol import llm_param


def test_prompt_cache_payload_uses_ttl_for_gpt56() -> None:
    assert build_prompt_cache_payload("gpt-5.6-sol", None) == {"prompt_cache_options": {"ttl": "30m"}}


def test_prompt_cache_payload_uses_ttl_for_gpt6() -> None:
    for model_id in ("gpt-6-astra", "gpt-6-astra:max", "gpt-6-sol", "gpt-6-luna:max"):
        assert build_prompt_cache_payload(model_id, None) == {"prompt_cache_options": {"ttl": "30m"}}


def test_prompt_cache_payload_uses_retention_for_older_gpt() -> None:
    assert build_prompt_cache_payload("gpt-5.5", None) == {"prompt_cache_retention": "24h"}


def test_prompt_cache_payload_respects_short_retention() -> None:
    assert build_prompt_cache_payload("gpt-5.6-sol", "short") == {}


def test_prompt_cache_payload_uses_long_retention_for_unknown_model() -> None:
    assert build_prompt_cache_payload("custom-model", "long") == {"prompt_cache_retention": "24h"}


def test_openai_payload_uses_inherited_cache_key_instead_of_fork_session_id() -> None:
    param = llm_param.LLMCallParameter(
        input=[],
        model_id="gpt-5.6-sol",
        session_id="fork-session",
        prompt_cache_key="source-session",
    )

    assert build_responses_payload(param)["prompt_cache_key"] == "source-session"
    assert build_codex_payload(param)["prompt_cache_key"] == "source-session"
