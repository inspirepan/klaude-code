from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from klaude_code.protocol.model import ConversationItem


class LLMClientProtocol(Enum):
    OPENAI = "openai"
    RESPONSES = "responses"
    OPENROUTER = "openrouter"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    CODEX = "codex"
    GOOGLE = "google"


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
    reasoning_effort: Literal["high", "medium", "low", "minimal", "none", "xhigh"] | None = None
    reasoning_summary: Literal["auto", "concise", "detailed"] | None = None

    # Claude/Gemini Thinking Style
    type: Literal["enabled", "disabled"] | None = None
    budget_tokens: int | None = None


class Cost(BaseModel):
    """Cost configuration per million tokens."""

    input: float  # Input token price per million tokens
    output: float  # Output token price per million tokens
    cache_read: float = 0.0  # Cache read price per million tokens
    cache_write: float = 0.0  # Cache write price per million tokens (ignored in calculation for now)
    currency: Literal["USD", "CNY"] = "USD"  # Currency for cost display


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


class LLMConfigModelParameter(BaseModel):
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    context_limit: int | None = None

    # OpenAI GPT-5
    verbosity: Literal["low", "medium", "high"] | None = None

    # Unified Thinking & Reasoning
    thinking: Thinking | None = None

    # OpenRouter Provider Routing Preferences
    provider_routing: OpenRouterProviderRouting | None = None

    # Cost configuration (USD per million tokens)
    cost: Cost | None = None


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
    input: list[ConversationItem]
    system: str | None = None
    tools: list[ToolSchema] | None = None
    session_id: str | None = None
