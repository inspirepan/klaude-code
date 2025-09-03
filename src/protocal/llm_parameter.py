from typing import Literal

from pydantic import BaseModel
from pydantic.json_schema import JsonSchemaValue

from src.protocal.model import ResponseItem


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


class LLMConfigParameter(BaseModel):
    """
    Parameter support in config JSON
    """

    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    is_azure: bool = False
    azure_api_version: str | None = None

    temperature: float | None = None
    max_tokens: int | None = None

    # OpenAI Reasoning
    reasoning: Reasoning | None = None

    # Claude Extended Thinking
    thinking: Thinking | None = None


class LLMCallParameter(LLMConfigParameter):
    input: list[ResponseItem]
    system: str | None = None
    tools: list[ToolSchema] | None = None
    stream: Literal[True] = True  # Always True

    # OpenAI Responses
    include: list[str] | None = None
    store: bool = True
    previous_response_id: str | None = None


def merge_llm_parameter(
    param: LLMCallParameter, config: LLMConfigParameter
) -> LLMCallParameter:
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
    return param
