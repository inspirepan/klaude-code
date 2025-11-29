import time

import openai.types

from klaude_code.protocol import model


class MetadataTracker:
    """Tracks timing and metadata for LLM responses."""

    def __init__(self) -> None:
        self._request_start_time: float = time.time()
        self._first_token_time: float | None = None
        self._last_token_time: float | None = None
        self._metadata_item = model.ResponseMetadataItem()

    @property
    def metadata_item(self) -> model.ResponseMetadataItem:
        return self._metadata_item

    @property
    def first_token_time(self) -> float | None:
        return self._first_token_time

    @property
    def last_token_time(self) -> float | None:
        return self._last_token_time

    def record_token(self) -> None:
        """Record a token arrival, updating first/last token times."""
        now = time.time()
        if self._first_token_time is None:
            self._first_token_time = now
        self._last_token_time = now

    def set_usage(self, usage: model.Usage) -> None:
        """Set the usage information."""
        self._metadata_item.usage = usage

    def set_model_name(self, model_name: str) -> None:
        """Set the model name."""
        self._metadata_item.model_name = model_name

    def set_provider(self, provider: str) -> None:
        """Set the provider name."""
        self._metadata_item.provider = provider

    def set_response_id(self, response_id: str | None) -> None:
        """Set the response ID."""
        self._metadata_item.response_id = response_id

    def finalize(self) -> model.ResponseMetadataItem:
        """Finalize and return the metadata item with calculated performance metrics."""
        if self._metadata_item.usage and self._first_token_time is not None:
            self._metadata_item.usage.first_token_latency_ms = (
                self._first_token_time - self._request_start_time
            ) * 1000

            if self._last_token_time is not None and self._metadata_item.usage.output_tokens > 0:
                time_duration = self._last_token_time - self._first_token_time
                if time_duration >= 0.15:
                    self._metadata_item.usage.throughput_tps = self._metadata_item.usage.output_tokens / time_duration

        return self._metadata_item


def convert_usage(usage: openai.types.CompletionUsage, context_limit: int | None = None) -> model.Usage:
    """Convert OpenAI CompletionUsage to internal Usage model."""
    total_tokens = usage.total_tokens
    context_usage_percent = (total_tokens / context_limit) * 100 if context_limit else None
    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(usage.completion_tokens_details.reasoning_tokens if usage.completion_tokens_details else 0)
        or 0,
        output_tokens=usage.completion_tokens,
        total_tokens=total_tokens,
        context_usage_percent=context_usage_percent,
        throughput_tps=None,
        first_token_latency_ms=None,
    )
