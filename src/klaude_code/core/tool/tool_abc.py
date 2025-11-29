import string
from abc import ABC, abstractmethod
from pathlib import Path

from klaude_code.protocol import llm_param, model


def load_desc(path: Path, substitutions: dict[str, str] | None = None) -> str:
    """Load a tool description from a file, with optional substitutions."""
    description = path.read_text(encoding="utf-8")
    if substitutions:
        description = string.Template(description).substitute(substitutions)
    return description


class ToolABC(ABC):
    @classmethod
    @abstractmethod
    def schema(cls) -> llm_param.ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        raise NotImplementedError
