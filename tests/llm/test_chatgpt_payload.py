from typing import Any, cast

from klaude_code.const import CHATGPT_API_BASE_URL, CHATGPT_USAGE_SETTINGS_URL
from klaude_code.llm.chatgpt.client import (
    PROMPT_CACHE_KEY_MAX_LENGTH,
    _usage_limit_message,
    build_payload,
    cache_affinity_id,
)
from klaude_code.protocol import llm_param


def _build(**overrides: Any) -> dict[str, Any]:
    param = llm_param.LLMCallParameter(input=[], model_id="gpt-5.6-sol", **overrides)
    return cast(dict[str, Any], build_payload(param))


def test_uses_public_responses_endpoint() -> None:
    assert CHATGPT_API_BASE_URL == "https://api.openai.com/v1"


def test_verbosity_defaults_to_low() -> None:
    assert _build()["text"] == {"verbosity": "low"}


def test_verbosity_max_maps_to_high() -> None:
    assert _build(verbosity="max")["text"] == {"verbosity": "high"}


def test_prompt_cache_key_is_clamped_to_64_chars() -> None:
    long_key = "s" * (PROMPT_CACHE_KEY_MAX_LENGTH + 10)
    payload = _build(session_id=long_key)
    assert payload["prompt_cache_key"] == "s" * PROMPT_CACHE_KEY_MAX_LENGTH


def test_cache_affinity_id_prefers_inherited_key() -> None:
    # Forked/cache-safe paths inherit the parent's prompt_cache_key while the
    # fork gets a fresh session id; the affinity identity must follow the key.
    param = llm_param.LLMCallParameter(
        input=[],
        model_id="gpt-5.6-sol",
        session_id="fork-session",
        prompt_cache_key="source-session",
    )
    assert cache_affinity_id(param) == "source-session"
    param_no_key = llm_param.LLMCallParameter(input=[], model_id="gpt-5.6-sol", session_id="abc")
    assert cache_affinity_id(param_no_key) == "abc"
    param_none = llm_param.LLMCallParameter(input=[], model_id="gpt-5.6-sol")
    assert cache_affinity_id(param_none) is None


def test_payload_never_sends_cache_retention_fields() -> None:
    payload = _build(cache_retention="long", session_id="session")
    assert "prompt_cache_retention" not in payload
    assert "prompt_cache_options" not in payload


def test_usage_limit_message_links_to_chatgpt_settings() -> None:
    message = _usage_limit_message(RuntimeError("subscription_sharing_usage_limit_exceeded"))
    assert CHATGPT_USAGE_SETTINGS_URL in message


def test_other_errors_are_unchanged() -> None:
    assert _usage_limit_message(RuntimeError("boom")) == "boom"
