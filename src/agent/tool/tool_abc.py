from abc import ABC, abstractmethod

from src.protocol.llm_parameter import ToolSchema
from src.protocol.model import ToolMessage


class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> ToolMessage:
        raise NotImplementedError
