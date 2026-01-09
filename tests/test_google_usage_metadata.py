from __future__ import annotations

from google.genai.types import GenerateContentResponseUsageMetadata

from klaude_code.llm.google.client import _usage_from_metadata  # pyright: ignore[reportPrivateUsage]


def test_google_usage_prompt_includes_cached_tokens() -> None:
    usage_metadata = GenerateContentResponseUsageMetadata(
        prompt_token_count=58_451,
        cached_content_token_count=50_498,
        candidates_token_count=134,
        total_token_count=58_585,
    )

    usage = _usage_from_metadata(usage_metadata, context_limit=None, max_tokens=None)
    assert usage is not None
    assert usage.input_tokens == 58_451
    assert usage.cached_tokens == 50_498
    assert usage.output_tokens == 134
    assert usage.context_size == 58_585
