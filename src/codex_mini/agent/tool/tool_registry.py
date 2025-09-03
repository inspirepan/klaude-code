from typing import Callable, TypeVar

from codex_mini.agent.tool.tool_abc import ToolABC
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ContentPart, ToolCallItem, ToolMessage

_REGISTRY: dict[str, type[ToolABC]] = {}

T = TypeVar("T", bound=ToolABC)


def register(name: str) -> Callable[[type[T]], type[T]]:
    def _decorator(cls: type[T]) -> type[T]:
        _REGISTRY[name] = cls
        return cls

    return _decorator


def clients() -> list[str]:
    return list(_REGISTRY.keys())


def get_tool_schemas(tool_names: list[str]) -> list[ToolSchema]:
    schemas: list[ToolSchema] = []
    for tool_name in tool_names:
        if tool_name not in _REGISTRY:
            raise ValueError(f"Unknown Tool: {tool_name}")
        schemas.append(_REGISTRY[tool_name].schema())
    return schemas


async def run_tool(tool_call: ToolCallItem) -> ToolMessage:
    if tool_call.name not in _REGISTRY:
        return ToolMessage(
            call_id=tool_call.call_id,
            content=[ContentPart(text=f"Tool {tool_call.name} not exists")],
            status="error",
        )
    try:
        tool_message = await _REGISTRY[tool_call.name].call(tool_call.arguments)
        tool_message.call_id = tool_call.call_id
        return tool_message
    except Exception as e:
        return ToolMessage(
            call_id=tool_call.call_id,
            content=[ContentPart(text=f"Tool {tool_call.name} execution error: {e}")],
            status="error",
        )
