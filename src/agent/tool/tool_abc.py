from abc import ABC, abstractmethod

from src.protocal.llm_parameter import ToolSchema
from src.protocal.model import ToolMessage


class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> ToolMessage:
        raise NotImplementedError
