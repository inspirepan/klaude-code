"""
update_plan tool: Codex variant of todo_write tool
"""

from pathlib import Path

from pydantic import BaseModel, field_validator

from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_context import get_current_todo_context
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

from .todo_write_tool import get_new_completed_todos


class PlanItemArguments(BaseModel):
    step: str
    status: model.TodoStatusType

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


@register(tools.UPDATE_PLAN)
class UpdatePlanTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.UPDATE_PLAN,
            type="function",
            description=load_desc(Path(__file__).parent / "update_plan_tool.md"),
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
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = UpdatePlanArguments.model_validate_json(arguments)
        except ValueError as exc:
            return model.ToolResultItem(status="error", output=f"Invalid arguments: {exc}")

        todo_context = get_current_todo_context()
        if todo_context is None:
            return model.ToolResultItem(status="error", output="No active session found")

        new_todos = [model.TodoItem(content=item.step, status=item.status) for item in args.plan]
        old_todos = todo_context.get_todos()
        new_completed = get_new_completed_todos(old_todos, new_todos)
        todo_context.set_todos(new_todos)

        ui_extra = model.TodoUIExtra(todos=new_todos, new_completed=new_completed)

        return model.ToolResultItem(
            status="success",
            output="Plan updated",
            ui_extra=model.TodoListUIExtra(todo_list=ui_extra),
            side_effects=[model.ToolSideEffect.TODO_CHANGE],
        )
