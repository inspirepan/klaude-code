import asyncio
import re
from typing import Any, cast

import httpx

from klaude_code.const import CODEX_USER_AGENT
from klaude_code.llm.openai_codex.client import (
    CODEX_HEADERS,
    PROMPT_CACHE_KEY_MAX_LENGTH,
    build_payload,
    cache_affinity_id,
    strip_stainless_headers,
)
from klaude_code.protocol import llm_param


def _build(**overrides: Any) -> dict[str, Any]:
    param = llm_param.LLMCallParameter(input=[], model_id="gpt-5.6-sol", **overrides)
    return cast(dict[str, Any], build_payload(param))


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
    # The Codex backend rejects prompt_cache_options with 400; pi sends neither
    # retention field on this path.
    payload = _build(cache_retention="long", session_id="session")
    assert "prompt_cache_retention" not in payload
    assert "prompt_cache_options" not in payload


def test_codex_headers_match_pi() -> None:
    assert CODEX_HEADERS["Accept"] == "text/event-stream"
    assert CODEX_HEADERS["originator"] == "pi"
    assert CODEX_HEADERS["OpenAI-Beta"] == "responses=experimental"
    # pi formats the UA as `pi (<platform> <release>; <arch>)`.
    assert re.fullmatch(r"pi \(.+ .+; .+\)", CODEX_USER_AGENT)


def test_strip_stainless_headers() -> None:
    async def _run() -> None:
        request = httpx.Request(
            "POST",
            "https://chatgpt.com/backend-api/codex/responses",
            headers={
                "X-Stainless-Lang": "python",
                "X-Stainless-OS": "MacOS",
                "Accept": "text/event-stream",
            },
        )
        await strip_stainless_headers(request)
        assert "x-stainless-lang" not in request.headers
        assert "x-stainless-os" not in request.headers
        assert request.headers["accept"] == "text/event-stream"

    asyncio.run(_run())
