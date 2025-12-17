import string
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
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
    def metadata(cls) -> "ToolMetadata":
        return ToolMetadata()

    @classmethod
    @abstractmethod
    def schema(cls) -> llm_param.ToolSchema:
        raise NotImplementedError

    @classmethod
    @abstractmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        raise NotImplementedError


class ToolConcurrencyPolicy(str, Enum):
    SEQUENTIAL = "sequential"
    CONCURRENT = "concurrent"


@dataclass(frozen=True)
class ToolMetadata:
    concurrency_policy: ToolConcurrencyPolicy = ToolConcurrencyPolicy.SEQUENTIAL
    has_side_effects: bool = False
    requires_tool_context: bool = True
