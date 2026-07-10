from openai.types.responses.response_create_params import ResponseCreateParamsBase

from klaude_code.protocol.model_id import supports_extended_prompt_cache, supports_prompt_cache_options_ttl


def build_prompt_cache_payload(model_id: str | None, cache_retention: str | None) -> ResponseCreateParamsBase:
    """Build OpenAI prompt cache parameters for Responses-compatible requests."""
    if cache_retention == "short":
        return {}
    if supports_prompt_cache_options_ttl(model_id):
        return {"prompt_cache_options": {"ttl": "30m"}}
    if cache_retention == "long" or supports_extended_prompt_cache(model_id):
        return {"prompt_cache_retention": "24h"}
    return {}
