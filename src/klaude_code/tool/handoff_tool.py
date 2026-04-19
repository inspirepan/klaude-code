from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register


class HandoffArguments(BaseModel):
    goal: str = Field(description="What the fresh context should focus on - describe what needs to happen next")


@register(tools.HANDOFF)
class HandoffTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.HANDOFF,
            type="function",
            description=load_desc(Path(__file__).parent / "handoff_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "What the fresh context should focus on - describe what needs to happen next",
                    },
                },
                "required": ["goal"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = HandoffArguments.model_validate_json(arguments)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")

        handoff_manager = context.handoff_manager
        if handoff_manager is None:
            return message.ToolResultMessage(
                status="error",
                output_text="Handoff is not available in this context",
            )

        try:
            result = handoff_manager.send_handoff(args.goal)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        return message.ToolResultMessage(status="success", output_text=result)
