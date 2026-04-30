from datetime import datetime

from pydantic import BaseModel, Field, computed_field

from klaude_code.const import DEFAULT_MAX_TOKENS


class Usage(BaseModel):
    # Token usage (primary state)
    input_tokens: int = 0
    cached_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    output_tokens: int = 0

    # Context window tracking
    context_size: int | None = None
    context_limit: int | None = None
    max_tokens: int | None = None

    throughput_tps: float | None = None
    first_token_latency_ms: float | None = None
    cache_hit_rate: float | None = None

    # Cost (calculated from token counts and cost config)
    input_cost: float | None = None
    output_cost: float | None = None
    cache_read_cost: float | None = None
    currency: str = "USD"
    response_id: str | None = None
    model_name: str = ""
    provider: str | None = None
    task_duration_s: float | None = None
    created_at: datetime = Field(default_factory=datetime.now)

    @computed_field
    @property
    def total_tokens(self) -> int:
        """Total tokens computed from input + output tokens."""
        return self.input_tokens + self.output_tokens

    @computed_field
    @property
    def total_cost(self) -> float | None:
        """Total cost computed from input + output + cache_read costs."""
        costs = [self.input_cost, self.output_cost, self.cache_read_cost]
        non_none = [cost for cost in costs if cost is not None]
        if not non_none:
            return None
        total = sum(non_none)
        if total == 0 and not any(
            (
                self.input_tokens,
                self.cached_tokens,
                self.cache_write_tokens,
                self.output_tokens,
                self.reasoning_tokens,
            )
        ):
            return None
        return total

    @computed_field
    @property
    def context_usage_percent(self) -> float | None:
        """Context usage percentage computed from context_size / effective limit."""
        if self.context_limit is None or self.context_limit <= 0:
            return None
        if self.context_size is None:
            return None
        effective_limit = self.context_limit - (self.max_tokens or DEFAULT_MAX_TOKENS)
        if effective_limit <= 0:
            return None
        return (self.context_size / effective_limit) * 100


__all__ = ["Usage"]
