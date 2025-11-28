from typing import Callable, TypeVar

from klaude_code.core.sub_agent import get_sub_agent_profile, iter_sub_agent_profiles, sub_agent_tool_names
from klaude_code.core.tool.sub_agent_tool import SubAgentTool
from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.protocol import tools
from klaude_code.protocol.llm_parameter import ToolSchema

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


def get_tool_schemas(tool_names: list[str]) -> list[ToolSchema]:
    schemas: list[ToolSchema] = []
    for tool_name in tool_names:
        if tool_name not in _REGISTRY:
            raise ValueError(f"Unknown Tool: {tool_name}")
        schemas.append(_REGISTRY[tool_name].schema())
    return schemas


def get_registry() -> dict[str, type[ToolABC]]:
    """Get the global tool registry."""
    return _REGISTRY


def get_vanilla_tools() -> list[ToolSchema]:
    base_tool_names = [
        tools.BASH,
        tools.EDIT,
        tools.WRITE,
        tools.READ,
    ]
    return get_tool_schemas(base_tool_names)


def get_main_agent_tools(model_name: str) -> list[ToolSchema]:
    def _base_main_tools(name: str) -> list[str]:
        if "gpt-5" in name:
            return [
                tools.BASH,
                tools.READ,
                tools.APPLY_PATCH,
                tools.UPDATE_PLAN,
            ]
        return [
            tools.BASH,
            tools.READ,
            tools.EDIT,
            tools.WRITE,
            tools.TODO_WRITE,
        ]

    tool_names = _base_main_tools(model_name)
    tool_names.extend(sub_agent_tool_names(enabled_only=True, model_name=model_name))
    tool_names.extend(
        [
            tools.SKILL,
            tools.MERMAID,
            tools.MEMORY,
        ]
    )
    return get_tool_schemas(tool_names)


def get_sub_agent_tools(model_name: str, sub_agent_type: tools.SubAgentType) -> list[ToolSchema]:
    profile = get_sub_agent_profile(sub_agent_type)
    if not profile.enabled_for_model(model_name):
        return []
    return get_tool_schemas(list(profile.tool_set))
