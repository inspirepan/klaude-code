from typing import Callable, TypeVar

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolCallItem, ToolResultItem
from codex_mini.protocol import tools

_REGISTRY: dict[str, type[ToolABC]] = {}

T = TypeVar("T", bound=ToolABC)


def register(name: str) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def list_tools() -> list[str]:
    return list(_REGISTRY.keys())


def get_tool_schemas(tool_names: list[str]) -> list[ToolSchema]:
    schemas: list[ToolSchema] = []
    for tool_name in tool_names:
        if tool_name not in _REGISTRY:
            raise ValueError(f"Unknown Tool: {tool_name}")
        schemas.append(_REGISTRY[tool_name].schema())
    return schemas


async def run_tool(tool_call: ToolCallItem) -> ToolResultItem:
    if tool_call.name not in _REGISTRY:
        return ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} not exists",
            status="error",
            tool_name=tool_call.name,
        )
    try:
        tool_result = await _REGISTRY[tool_call.name].call(tool_call.arguments)
        tool_result.call_id = tool_call.call_id
        tool_result.tool_name = tool_call.name
        return tool_result
    except Exception as e:
        return ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} execution error: {e.__class__.__name__} {e}",
            status="error",
            tool_name=tool_call.name,
        )


def get_main_agent_tools(model_name: str) -> list[ToolSchema]:
    if "gpt-5" in model_name:
        return get_tool_schemas(
            [
                # tools.TODO_WRITE,
                tools.BASH,
                tools.READ,
                tools.EDIT,
                tools.MULTI_EDIT,
                tools.EXIT_PLAN_MODE,
                # tools.TASK,
            ]
        )
    return get_tool_schemas(
        [
            tools.TODO_WRITE,
            tools.BASH,
            tools.READ,
            tools.EDIT,
            tools.MULTI_EDIT,
            tools.EXIT_PLAN_MODE,
            tools.TASK,
        ]
    )


def get_sub_agent_tools(model_name: str) -> list[ToolSchema]:
    return get_tool_schemas([tools.BASH, tools.READ, tools.EDIT, tools.MULTI_EDIT])
