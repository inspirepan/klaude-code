from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_exit_plan_mode_callback
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol import model
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.tools import EXIT_PLAN_MODE


class ExitPlanModeArguments(BaseModel):
    plan: str


@register(EXIT_PLAN_MODE)
class ExitPlanModeTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=EXIT_PLAN_MODE,
            type="function",
            description="""Use this tool when you are in plan mode and have finished presenting your plan and are ready to code. This will prompt the user to exit plan mode.
IMPORTANT: Only use this tool when the task requires planning the implementation steps of a task that requires writing code. For research tasks where you're gathering information, searching files, reading files or in general trying to understand the codebase - do NOT use this tool.

Eg.

Initial task: "Search for and understand the implementation of vim mode in the codebase" - Do not use the exit plan mode tool because you are not planning the implementation steps of a task.
Initial task: "Help me implement yank mode for vim" - Use the exit plan mode tool after you have finished planning the implementation steps of the task.
""",
            parameters={
                "type": "object",
                "properties": {
                    "plan": {
                        "type": "string",
                        "description": """The plan you came up with, that you want to run by the user for approval. Supports markdown. The plan should be pretty concise.""",
                    }
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            _ = ExitPlanModeArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        # Call current agent's deactivate_plan_mode via handle
        deactivate = current_exit_plan_mode_callback.get()
        if deactivate is None:
            return model.ToolResultItem(
                status="error",
                output="No active agent found",
            )
        msg = deactivate()
        return model.ToolResultItem(
            status="success",
            output="User has approved your plan. You can now start coding. Start with updating your todo list if applicable.",
            ui_extra=msg,
        )
