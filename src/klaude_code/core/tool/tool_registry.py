from collections.abc import Callable
from typing import TypeVar

from klaude_code.core.tool.sub_agent_tool import SubAgentTool
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.protocol import llm_param, tools
from klaude_code.protocol.sub_agent import get_sub_agent_profile, iter_sub_agent_profiles, sub_agent_tool_names

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


def load_agent_tools(
    model_name: str, sub_agent_type: tools.SubAgentType | None = None, *, vanilla: bool = False
) -> list[llm_param.ToolSchema]:
    """Get tools for an agent based on model and agent type.

    Args:
        model_name: The model name.
        sub_agent_type: If None, returns main agent tools. Otherwise returns sub-agent tools.
        vanilla: If True, returns minimal vanilla tools (ignores sub_agent_type).
    """
    if vanilla:
        return get_tool_schemas([tools.BASH, tools.EDIT, tools.WRITE, tools.READ])

    if sub_agent_type is not None:
        profile = get_sub_agent_profile(sub_agent_type)
        return get_tool_schemas(list(profile.tool_set))

    # Main agent tools
    if "gpt-5" in model_name:
        tool_names = [tools.BASH, tools.READ, tools.APPLY_PATCH, tools.MOVE, tools.UPDATE_PLAN]
    elif "gemini-3" in model_name:
        tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.MOVE]
    else:
        tool_names = [tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.MOVE, tools.TODO_WRITE]

    tool_names.extend(sub_agent_tool_names(enabled_only=True, model_name=model_name))
    tool_names.extend([tools.SKILL, tools.MERMAID])
    # tool_names.extend([tools.MEMORY])
    return get_tool_schemas(tool_names)
