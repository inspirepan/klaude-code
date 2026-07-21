from openai.types.responses.response_create_params import ResponseCreateParamsBase

from klaude_code.protocol.model_id import supports_extended_prompt_cache, supports_prompt_cache_options_ttl


def build_prompt_cache_payload(
    model_id: str | None,
    cache_retention: str | None,
    *,
    allow_ttl_options: bool = True,
) -> ResponseCreateParamsBase:
    """Build OpenAI prompt cache parameters for Responses-compatible requests.

    The Codex (ChatGPT OAuth) backend rejects prompt_cache_options with 400,
    so callers on that path pass allow_ttl_options=False.
    """
    if cache_retention == "short":
        return {}
    if allow_ttl_options and supports_prompt_cache_options_ttl(model_id):
        return {"prompt_cache_options": {"ttl": "30m"}}
    if cache_retention == "long" or supports_extended_prompt_cache(model_id):
        return {"prompt_cache_retention": "24h"}
    return {}
