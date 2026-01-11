import time
from collections.abc import AsyncGenerator

import openai.types

from klaude_code.const import THROUGHPUT_MIN_DURATION_SEC
from klaude_code.llm.client import LLMStreamABC
from klaude_code.protocol import llm_param, message, model


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
    non_cached_input = max(0, usage.input_tokens - usage.cached_tokens)
    usage.input_cost = (non_cached_input / 1_000_000) * cost_config.input

    # Output tokens cost (includes reasoning tokens)
    usage.output_cost = (usage.output_tokens / 1_000_000) * cost_config.output

    # Cache read cost
    usage.cache_read_cost = (usage.cached_tokens / 1_000_000) * (cost_config.cache_read or cost_config.input)

    # Image generation cost
    usage.image_cost = (usage.image_tokens / 1_000_000) * cost_config.image


class MetadataTracker:
    """Tracks timing and metadata for LLM responses."""

    def __init__(self, cost_config: llm_param.Cost | None = None) -> None:
        self._request_start_time: float = time.time()
        self._first_token_time: float | None = None
        self._last_token_time: float | None = None
        self._usage = model.Usage()
        self._cost_config = cost_config

    def record_token(self) -> None:
        """Record a token arrival, updating first/last token times."""
        now = time.time()
        if self._first_token_time is None:
            self._first_token_time = now
        self._last_token_time = now

    def set_usage(self, usage: model.Usage) -> None:
        """Set the usage information."""
        preserved = {
            "response_id": self._usage.response_id,
            "model_name": self._usage.model_name,
            "provider": self._usage.provider,
            "task_duration_s": self._usage.task_duration_s,
            "created_at": self._usage.created_at,
        }
        self._usage = usage.model_copy(update=preserved)

    def set_model_name(self, model_name: str) -> None:
        """Set the model name."""
        self._usage.model_name = model_name

    def set_provider(self, provider: str) -> None:
        """Set the provider name."""
        self._usage.provider = provider

    def set_response_id(self, response_id: str | None) -> None:
        """Set the response ID."""
        self._usage.response_id = response_id

    def finalize(self) -> model.Usage:
        """Finalize and return the usage item with calculated performance metrics."""
        if self._first_token_time is not None:
            self._usage.first_token_latency_ms = (self._first_token_time - self._request_start_time) * 1000

            if self._last_token_time is not None and self._usage.output_tokens > 0:
                time_duration = self._last_token_time - self._request_start_time
                if time_duration >= THROUGHPUT_MIN_DURATION_SEC:
                    self._usage.throughput_tps = self._usage.output_tokens / time_duration

        # Calculate cost if config is available
        calculate_cost(self._usage, self._cost_config)

        return self._usage

    @property
    def usage(self) -> model.Usage:
        return self._usage


def error_stream_items(
    metadata_tracker: MetadataTracker,
    *,
    error: str,
    response_id: str | None = None,
) -> list[message.LLMStreamItem]:
    metadata_tracker.set_response_id(response_id)
    metadata = metadata_tracker.finalize()
    return [
        message.StreamErrorItem(error=error),
        message.AssistantMessage(parts=[], response_id=response_id, usage=metadata),
    ]


class ErrorLLMStream(LLMStreamABC):
    """LLMStream implementation for error scenarios."""

    def __init__(self, items: list[message.LLMStreamItem]) -> None:
        self._items = list(items)

    def __aiter__(self) -> AsyncGenerator[message.LLMStreamItem]:
        return self._iterate()

    async def _iterate(self) -> AsyncGenerator[message.LLMStreamItem]:
        for item in self._items:
            yield item

    def get_partial_message(self) -> message.AssistantMessage | None:
        return None


def error_llm_stream(
    metadata_tracker: MetadataTracker,
    *,
    error: str,
    response_id: str | None = None,
) -> ErrorLLMStream:
    """Create an LLMStream that yields error items."""
    items = error_stream_items(metadata_tracker, error=error, response_id=response_id)
    return ErrorLLMStream(items)


def convert_usage(
    usage: openai.types.CompletionUsage,
    context_limit: int | None = None,
    max_tokens: int | None = None,
) -> model.Usage:
    """Convert OpenAI CompletionUsage to internal Usage model.

    context_token is set to total_tokens from the API response,
    representing the actual context window usage for this turn.
    """
    completion_details = usage.completion_tokens_details
    image_tokens = 0
    if completion_details is not None:
        image_tokens = getattr(completion_details, "image_tokens", 0) or 0

    return model.Usage(
        input_tokens=usage.prompt_tokens,
        cached_tokens=(usage.prompt_tokens_details.cached_tokens if usage.prompt_tokens_details else 0) or 0,
        reasoning_tokens=(completion_details.reasoning_tokens if completion_details else 0) or 0,
        output_tokens=usage.completion_tokens,
        image_tokens=image_tokens,
        context_size=usage.total_tokens,
        context_limit=context_limit,
        max_tokens=max_tokens,
    )
