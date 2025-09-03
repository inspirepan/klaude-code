from abc import ABC, abstractmethod

from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolMessage


class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> ToolMessage:
        raise NotImplementedError
