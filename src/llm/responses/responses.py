from collections.abc import AsyncGenerator
from typing import override

from src.config import Config
from src.llm.client import LLMClient
from src.llm.registry import register
from src.protocal.llm_parameter import LLMParameter
from src.protocal.model import AssistantMessage, ContentItem, ResponseItem


@register("responses")
class ResponsesClient(LLMClient):
    def __init__(self, config: Config):
        pass

    @classmethod
    @override
    def create(cls, config: Config) -> "LLMClient":
        return cls(config)

    @override
    async def Call(self, param: LLMParameter) -> AsyncGenerator[ResponseItem, None]:
        yield AssistantMessage(content=[ContentItem(text="Hello, World!")])
