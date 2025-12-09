"""ReportBackTool for sub-agents to return structured output."""

from typing import Any, ClassVar

from klaude_code.protocol import llm_param, model, tools


class ReportBackTool:
    """Special tool for sub-agents to return structured output and end the task.

    This tool is dynamically injected when a parent agent calls a sub-agent with
    an output_schema. The schema for this tool's parameters is defined by the
    parent agent, allowing structured data to be returned.

    Note: This class does not inherit from ToolABC because it's not registered
    in the global tool registry. Instead, it's handled specially by the
    TurnExecutor and SubAgentManager.
    """

    _schema: ClassVar[dict[str, Any]] = {}

    @classmethod
    def for_schema(cls, schema: dict[str, Any]) -> type["ReportBackTool"]:
        """Create a tool class with the specified output schema.

        Args:
            schema: JSON Schema defining the expected structure of the report_back arguments.

        Returns:
            A new class with the schema set as a class variable.
        """
        return type("ReportBackTool", (ReportBackTool,), {"_schema": schema})

    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        """Generate the tool schema for this report_back tool."""
        return llm_param.ToolSchema(
            name=tools.REPORT_BACK,
            type="function",
            description=(
                "Report the final structured result back to the parent agent. "
                "Call this when you have completed the task and want to return structured data. "
                "The task will end after this tool is called."
            ),
            parameters=cls._schema,
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        """Execute the report_back tool.

        The actual handling of report_back results is done by TurnExecutor.
        This method just returns a success status to maintain the tool call flow.
        """
        return model.ToolResultItem(
            status="success",
            output="Result reported successfully. Task will end.",
        )
