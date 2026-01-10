from collections.abc import Callable
from typing import TypeVar

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.protocol import llm_param

_REGISTRY: dict[str, type[ToolABC]] = {}

T = TypeVar("T", bound=ToolABC)


def register(name: str) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def get_tool_schemas(tool_names: list[str]) -> list[llm_param.ToolSchema]:
    schemas: list[llm_param.ToolSchema] = []
    for tool_name in tool_names:
        if tool_name not in _REGISTRY:
            raise ValueError(f"Unknown Tool: {tool_name}")
        schemas.append(_REGISTRY[tool_name].schema())
    return schemas


def get_registry() -> dict[str, type[ToolABC]]:
    """Get the global tool registry."""
    return _REGISTRY
