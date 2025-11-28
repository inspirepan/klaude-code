import asyncio

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.truncation import truncate_tool_output
from klaude_code.protocol.model import (
    ToolCallItem,
    ToolResultItem,
    ToolResultUIExtra,
    ToolResultUIExtraType,
    TruncationUIExtra,
)


async def run_tool(tool_call: ToolCallItem, registry: dict[str, type[ToolABC]]) -> ToolResultItem:
    """Execute a tool call and return the result.

    Args:
        tool_call: The tool call to execute.
        registry: The tool registry mapping tool names to tool classes.

    Returns:
        The result of the tool execution.
    """
    if tool_call.name not in registry:
        return ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} not exists",
            status="error",
            tool_name=tool_call.name,
        )
    try:
        tool_result = await registry[tool_call.name].call(tool_call.arguments)
        tool_result.call_id = tool_call.call_id
        tool_result.tool_name = tool_call.name
        if tool_result.output:
            truncation_result = truncate_tool_output(tool_result.output, tool_call)
            tool_result.output = truncation_result.output
            if truncation_result.was_truncated and truncation_result.saved_file_path:
                tool_result.ui_extra = ToolResultUIExtra(
                    type=ToolResultUIExtraType.TRUNCATION,
                    truncation=TruncationUIExtra(
                        saved_file_path=truncation_result.saved_file_path,
                        original_length=truncation_result.original_length,
                        truncated_length=truncation_result.truncated_length,
                    ),
                )
        return tool_result
    except asyncio.CancelledError:
        # Propagate cooperative cancellation so outer layers can handle interrupts correctly.
        raise
    except Exception as e:
        return ToolResultItem(
            call_id=tool_call.call_id,
            output=f"Tool {tool_call.name} execution error: {e.__class__.__name__} {e}",
            status="error",
            tool_name=tool_call.name,
        )
