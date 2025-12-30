import time

import openai.types

from klaude_code.protocol import llm_param, model


def calculate_cost(usage: model.Usage, cost_config: llm_param.Cost | None) -> None:
    """Calculate and set cost fields on usage based on cost configuration.

    Note: input_tokens includes cached_tokens, so we need to subtract cached_tokens
    to get the actual non-cached input tokens for cost calculation.
    """
    if cost_config is None:
        return

    # Set currency
    usage.currency = cost_config.currency

    # Non-cached input tokens cost
    non_cached_input = usage.input_tokens - usage.cached_tokens
    usage.input_cost = (non_cached_input / 1_000_000) * cost_config.input

    # Output tokens cost (includes reasoning tokens)
    usage.output_cost = (usage.output_tokens / 1_000_000) * cost_config.output

    # Cache read cost
    usage.cache_read_cost = (usage.cached_tokens / 1_000_000) * cost_config.cache_read


class MetadataTracker:
    """Tracks timing and metadata for LLM responses."""

    def __init__(self, cost_config: llm_param.Cost | None = None) -> None:
        self._request_start_time: float = time.time()
        self._first_token_time: float | None = None
        self._last_token_time: float | None = None
        self._metadata_item = model.ResponseMetadataItem()
        self._cost_config = cost_config

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
                time_duration = self._last_token_time - self._request_start_time
                if time_duration >= 0.15:
                    self._metadata_item.usage.throughput_tps = self._metadata_item.usage.output_tokens / time_duration

        # Calculate cost if config is available
        if self._metadata_item.usage:
            calculate_cost(self._metadata_item.usage, self._cost_config)

        return self._metadata_item


def convert_usage(
    usage: openai.types.CompletionUsage,
    context_limit: int | None = None,
    max_tokens: int | None = None,
) -> model.Usage:
    """Convert OpenAI CompletionUsage to internal Usage model.

    context_token is set to total_tokens from the API response,
    representing the actual context window usage for this turn.
    """
    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(usage.completion_tokens_details.reasoning_tokens if usage.completion_tokens_details else 0)
        or 0,
        output_tokens=usage.completion_tokens,
        context_size=usage.total_tokens,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )
