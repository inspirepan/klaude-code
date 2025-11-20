from abc import ABC, abstractmethod

from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import ToolResultItem


class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        raise NotImplementedError
