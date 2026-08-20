import re
from datetime import UTC, datetime
from enum import Enum
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, field_validator
from pydantic.json_schema import JsonSchemaValue

from klaude_code.protocol.message import Message


class LLMClientProtocol(Enum):
    OPENAI = "openai"
    RESPONSES = "responses"
    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    CODEX_OAUTH = "codex_oauth"
    XAI_OAUTH = "xai_oauth"
    GOOGLE = "google"
    GOOGLE_VERTEX = "google_vertex"


class ToolSchema(BaseModel):
    name: str
    type: Literal["function"]
    description: str
    parameters: JsonSchemaValue


class Thinking(BaseModel):
    """
    Unified Thinking & Reasoning Configuration
    """

    # OpenAI Reasoning Style
    reasoning_effort: Literal["high", "medium", "low", "minimal", "none", "xhigh", "max"] | None = None
    reasoning_mode: Literal["standard", "pro"] | None = None
    reasoning_context: Literal["auto", "current_turn", "all_turns"] | None = None
    reasoning_summary: Literal["auto", "concise", "detailed"] | None = None

    # Claude/Gemini Thinking Style
    type: Literal["enabled", "disabled", "adaptive"] | None = None
    budget_tokens: int | None = None


_TIME_WINDOW_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})$")

_COST_PRICE_FIELDS = ("input", "output", "cache_read", "cache_write")


@lru_cache(maxsize=64)
def parse_time_window(window: str) -> tuple[int, int]:
    """Parse a "HH:MM-HH:MM" window into minutes-from-midnight bounds."""
    match = _TIME_WINDOW_PATTERN.match(window.strip())
    if match is None:
        raise ValueError(f"invalid time window {window!r}, expected 'HH:MM-HH:MM'")
    start_hour, start_minute, end_hour, end_minute = (int(group) for group in match.groups())
    if start_hour > 24 or end_hour > 24 or start_minute > 59 or end_minute > 59:
        raise ValueError(f"invalid time window {window!r}, hour must be 0-24 and minute 0-59")
    return start_hour * 60 + start_minute, end_hour * 60 + end_minute


class PeakCost(BaseModel):
    """Peak-hour price override, per million tokens.

    `windows` are local clock ranges in `timezone` (e.g. "09:00-12:00"); a
    window may cross midnight ("22:00-02:00"). A price left at 0 keeps the
    off-peak price of the parent `Cost`.
    """

    windows: list[str] = []
    timezone: str = "Asia/Shanghai"
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0

    @field_validator("windows")
    @classmethod
    def _validate_windows(cls, windows: list[str]) -> list[str]:
        for window in windows:
            parse_time_window(window)
        return windows

    def is_active(self, when: datetime) -> bool:
        if not self.windows:
            return False
        try:
            local = when.astimezone(ZoneInfo(self.timezone))
        except (ZoneInfoNotFoundError, ValueError):
            # Missing tz database entry: fall back to the off-peak price.
            return False
        minutes = local.hour * 60 + local.minute
        for window in self.windows:
            start, end = parse_time_window(window)
            if start <= end:
                if start <= minutes < end:
                    return True
            elif minutes >= start or minutes < end:
                return True
        return False


class Cost(BaseModel):
    """Cost configuration per million tokens."""

    input: float = 0.0  # Input token price per million tokens
    output: float = 0.0  # Output token price per million tokens
    cache_read: float = 0.0  # Cache read price per million tokens
    cache_write: float = 0.0  # Cache write price per million tokens
    currency: Literal["USD", "CNY"] = "USD"  # Currency for cost display
    peak: PeakCost | None = None  # Time-of-day price override (e.g. DeepSeek peak hours)

    def at(self, when: datetime | None = None) -> "Cost":
        """Return the price table in effect at `when` (defaults to now)."""
        if self.peak is None:
            return self
        if not self.peak.is_active(when or datetime.now(UTC)):
            return self
        overrides: dict[str, Any] = {"peak": None}
        for field in _COST_PRICE_FIELDS:
            price = getattr(self.peak, field)
            if price > 0:
                overrides[field] = price
        return self.model_copy(update=overrides)


class OpenRouterProviderRouting(BaseModel):
    """
    https://openrouter.ai/docs/features/provider-routing#json-schema-for-provider-preferences
    """

    allow_fallbacks: bool | None = None
    require_parameters: bool | None = None

    # Data collection setting: allow (default) or deny
    data_collection: Literal["deny", "allow"] | None = None

    # Provider lists
    order: list[str] | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None

    # Quantization filters
    quantizations: list[Literal["int4", "int8", "fp4", "fp6", "fp8", "fp16", "bf16", "fp32", "unknown"]] | None = None

    # Sorting strategy when order is not specified
    sort: Literal["price", "throughput", "latency"] | None = None

    class MaxPrice(BaseModel):
        # USD price per million tokens (or provider-specific string); OpenRouter also
        # accepts other JSON types according to the schema, so Any covers that.
        prompt: float | str | Any | None = None
        completion: float | str | Any | None = None
        image: float | str | Any | None = None
        audio: float | str | Any | None = None
        request: float | str | Any | None = None

    max_price: MaxPrice | None = None

    class Experimental(BaseModel):
        # Placeholder for future experimental settings (no properties allowed in schema)
        pass

    experimental: Experimental | None = None


class LLMConfigProviderParameter(BaseModel):
    provider_name: str = ""
    protocol: LLMClientProtocol
    base_url: str | None = None
    api_key: str | None = None
    # Azure OpenAI
    is_azure: bool = False
    azure_api_version: str | None = None
    # AWS Bedrock configuration
    aws_access_key: str | None = None
    aws_secret_key: str | None = None
    aws_region: str | None = None
    aws_session_token: str | None = None
    aws_profile: str | None = None
    # Google Vertex AI configuration
    google_application_credentials: str | None = None
    google_cloud_project: str | None = None
    google_cloud_location: str | None = None


class LLMConfigModelParameter(BaseModel):
    model_id: str | None = None
    disabled: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    context_limit: int | None = None

    # Anthropic output_config.effort (controls intelligence vs cost tradeoff)
    effort: Literal["low", "medium", "high", "xhigh", "max"] | None = None

    # OpenAI GPT-5 text verbosity (controls response length/detail)
    verbosity: Literal["low", "medium", "high", "max"] | None = None

    # Unified Thinking & Reasoning
    thinking: Thinking | None = None

    # OpenRouter Provider Routing Preferences
    provider_routing: OpenRouterProviderRouting | None = None

    # Fast mode: Anthropic speed="fast", OpenAI service_tier="priority"
    fast_mode: bool = False

    # Prompt cache retention window.
    # - "short" (default): Anthropic cache_control ttl=5m / OpenAI in-memory prompt cache
    # - "long": Anthropic cache_control ttl=1h / OpenAI extended prompt cache when supported
    cache_retention: Literal["short", "long"] | None = None

    # Whether the model accepts image input. When False, image parts are
    # stripped from requests and replaced with text placeholders.
    supports_vision: bool = True

    # Cost configuration (USD per million tokens)
    cost: Cost | None = None

    @property
    def effective_effort(self) -> str | None:
        if self.thinking is not None and self.thinking.reasoning_effort is not None:
            return self.thinking.reasoning_effort
        return self.effort


class LLMConfigParameter(LLMConfigProviderParameter, LLMConfigModelParameter):
    """
    Parameter support in config yaml

    When adding a new parameter, please also modify the following:
    - llm_parameter.py#apply_config_defaults
    - llm/*/client.py, handle the new parameter, e.g. add it to extra_body
    - ui/repl_display.py#display_welcome
    - config/list_models.py#display_models_and_providers
    - config/select_model.py#select_model_from_config
    """

    pass


class LLMCallParameter(LLMConfigModelParameter):
    """
    Parameters for a single agent call
    """

    # Agent
    input: list[Message]
    system: str | None = None
    tools: list[ToolSchema] | None = None
    session_id: str | None = None
    prompt_cache_key: str | None = None
