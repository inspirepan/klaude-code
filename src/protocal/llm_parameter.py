from typing import List, Literal, Optional

from pydantic import BaseModel

from src.protocal import ResponseItem


class Tool(BaseModel):
    name: str
    type: Literal["function"]
    description: str
    parameters: dict


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


class LLMParameter(BaseModel):
    input: List[ResponseItem]
    model: str
    temperature: float = 1.0
    max_tokens: int = 8192
    stream: Literal[True] = True  # Always True
    tools: Optional[List[Tool]] = None

    # OpenAI Reasoning Model & Responses
    include: Optional[List[str]] = None
    reasoning: Optional[Reasoning] = None
    store: Literal[False] = False

    # Claude Extended Thinking
    thinking: Optional[Thinking] = None
