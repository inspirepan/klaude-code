from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from codex_mini.protocol.model import ConversationItem

DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPERATURE = 1.0
DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS = 2048


class LLMClientProtocol(Enum):
    OPENAI = "openai"
    RESPONSES = "responses"
    ANTHROPIC = "anthropic"


class ToolSchema(BaseModel):
    name: str
    type: Literal["function"]
    description: str
    parameters: JsonSchemaValue


class Reasoning(BaseModel):
    """
    OpenAI Reasoning Model
    """

    effort: Literal["high", "medium", "low", "minimal"]
    summary: Literal["auto", "concise", "detailed"] | None = None


class Thinking(BaseModel):
    """
    Claude Extended Thinking & Gemini Thinking
    """

    type: Literal["enabled", "disabled"] | None = None
    budget_tokens: int | None = None
    include_thoughts: bool | None = None


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


class OpenRouterPlugin(BaseModel):
    id: Literal["web"]
    # Web search, see: https://openrouter.ai/docs/features/web-search
    max_results: int | None = None
    search_prompt: str | None = None


class LLMConfigProviderParameter(BaseModel):
    provider_name: str = ""
    protocol: LLMClientProtocol
    base_url: str | None = None
    api_key: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None

    def is_openrouter(self) -> bool:
        return self.base_url == "https://openrouter.ai/api/v1"


class LLMConfigModelParameter(BaseModel):
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # OpenAI Reasoning
    reasoning: Reasoning | None = None

    # OpenAI GPT-5
    verbosity: Literal["low", "medium", "high"] | None = None

    # Claude Extended Thinking & Gemini Thinking
    thinking: Thinking | None = None

    # OpenRouter Provider Routing Preferences
    provider_routing: OpenRouterProviderRouting | None = None

    # OpenRouter Plugin (WebSearch etc.)
    plugins: list[OpenRouterPlugin] | None = None


class LLMConfigParameter(LLMConfigProviderParameter, LLMConfigModelParameter):
    """
    Parameter support in config yaml

    When adding a new parameter, please also modify the following:
    - llm_parameter.py#apply_config_defaults
    - llm/*/client.py, handle the new parameter, e.g. add it to extra_body
    - ui/repl_display.py#display_welcome
    - config/list_models.py#display_models_and_providers
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

    stream: Literal[True] = True  # Always True

    # OpenAI Responses
    include: list[str] | None = None
    store: bool = True
    previous_response_id: str | None = None


def apply_config_defaults(param: LLMCallParameter, config: LLMConfigParameter) -> LLMCallParameter:
    if param.model is None:
        param.model = config.model
    if param.temperature is None:
        param.temperature = config.temperature
    if param.max_tokens is None:
        param.max_tokens = config.max_tokens
    if param.reasoning is None:
        param.reasoning = config.reasoning
    if param.verbosity is None:
        param.verbosity = config.verbosity
    if param.thinking is None:
        param.thinking = config.thinking
    if param.provider_routing is None:
        param.provider_routing = config.provider_routing
    if param.plugins is None:
        param.plugins = config.plugins

    if param.model is None:
        raise ValueError("Model is required")
    if param.max_tokens is None:
        param.max_tokens = DEFAULT_MAX_TOKENS
    if param.temperature is None:
        param.temperature = DEFAULT_TEMPERATURE
    if param.thinking is not None and param.thinking.type == "enabled" and param.thinking.budget_tokens is None:
        param.thinking.budget_tokens = DEFAULT_ANTHROPIC_THINKING_BUDGET_TOKENS

    if param.model in {"gpt-5-2025-08-07", "gpt-5"}:
        param.temperature = 1.0  # Required for GPT-5

    return param
