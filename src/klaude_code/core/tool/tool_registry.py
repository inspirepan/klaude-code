from collections.abc import Callable
from typing import TypeVar

from klaude_code.core.tool.sub_agent_tool import SubAgentTool
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.protocol import llm_param
from klaude_code.protocol.sub_agent import iter_sub_agent_profiles

_REGISTRY: dict[str, type[ToolABC]] = {}

T = TypeVar("T", bound=ToolABC)


def register(name: str) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def _register_sub_agent_tools() -> None:
    """Automatically register all sub-agent tools based on their profiles."""
    for profile in iter_sub_agent_profiles():
        tool_cls = SubAgentTool.for_profile(profile)
        _REGISTRY[profile.name] = tool_cls


_register_sub_agent_tools()


def list_tools() -> list[str]:
    return list(_REGISTRY.keys())


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
