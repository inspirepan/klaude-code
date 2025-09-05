from enum import Enum
from typing import Literal

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from codex_mini.protocol.model import ConversationItem

DEFAULT_MAX_TOKENS = 8192
DEFAULT_TEMPERATURE = 1.0


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
    summary: Literal["auto", "concise", "detailed"]


class Thinking(BaseModel):
    """
    Claude Extended Thinking
    """

    type: Literal["enabled", "disabled"]
    budget_tokens: int


class LLMConfigProviderParameter(BaseModel):
    protocol: LLMClientProtocol
    base_url: str | None = None
    api_key: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None


class LLMConfigModelParameter(BaseModel):
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None

    # OpenAI Reasoning
    reasoning: Reasoning | None = None

    # OpenAI GPT-5
    verbosity: Literal["low", "medium", "high"] | None = None

    # Claude Extended Thinking
    thinking: Thinking | None = None


class LLMConfigParameter(LLMConfigProviderParameter, LLMConfigModelParameter):
    """
    Parameter support in config yaml
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
    if param.thinking is None:
        param.thinking = config.thinking

    if param.model is None:
        raise ValueError("Model is required")
    if param.max_tokens is None:
        param.max_tokens = DEFAULT_MAX_TOKENS
    if param.temperature is None:
        param.temperature = DEFAULT_TEMPERATURE

    if param.model in {"gpt-5-2025-08-07", "gpt-5"}:
        param.temperature = 1.0  # Required for GPT-5

    return param
