"""
update_plan tool: Codex variant of todo_write tool
"""

from pydantic import BaseModel, field_validator

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_session_var
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import TodoItem, TodoStatusType, TodoUIExtra, ToolResultItem
from codex_mini.protocol.tools import UPDATE_PLAN

from .todo_write_tool import get_new_completed_todos


class PlanItemArguments(BaseModel):
    step: str
    status: TodoStatusType

    @field_validator("step")
    @classmethod
    def validate_step(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("step must be a non-empty string")
        return value


class UpdatePlanArguments(BaseModel):
    plan: list[PlanItemArguments]
    explanation: str | None = None

    @field_validator("plan")
    @classmethod
    def validate_plan(cls, value: list[PlanItemArguments]) -> list[PlanItemArguments]:
        if not value:
            raise ValueError("plan must contain at least one item")
        in_progress_count = sum(1 for item in value if item.status == "in_progress")
        if in_progress_count > 1:
            raise ValueError("plan can have at most one in_progress step")
        return value


@register(UPDATE_PLAN)
class UpdatePlanTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=UPDATE_PLAN,
            type="function",
            description=(
                "Updates the task plan.\n"
                "Provide an optional explanation and a list of plan items, each with a step and status.\n"
                "At most one step can be in_progress at a time."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "explanation": {
                        "type": "string",
                        "description": "Optional explanation for the current plan state.",
                    },
                    "plan": {
                        "type": "array",
                        "description": "The list of steps",
                        "items": {
                            "type": "object",
                            "properties": {
                                "step": {"type": "string", "minLength": 1},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "completed"],
                                },
                            },
                            "required": ["step", "status"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["plan"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = UpdatePlanArguments.model_validate_json(arguments)
        except ValueError as exc:
            return ToolResultItem(status="error", output=f"Invalid arguments: {exc}")

        session = current_session_var.get()
        if session is None:
            return ToolResultItem(status="error", output="No active session found")

        new_todos = [TodoItem(content=item.step, status=item.status) for item in args.plan]
        new_completed = get_new_completed_todos(session.todos, new_todos)
        session.todos = new_todos

        ui_extra = TodoUIExtra(todos=new_todos, new_completed=new_completed)

        return ToolResultItem(
            status="success",
            output="Plan updated",
            ui_extra=ui_extra.model_dump_json(),
        )
