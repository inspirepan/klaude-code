from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools


class BacktrackArguments(BaseModel):
    checkpoint_id: int = Field(description="The checkpoint ID to revert to")
    note: str = Field(description="A note to your future self with key findings/context to preserve")
    rationale: str = Field(description="Why you are performing this backtrack")


@register(tools.BACKTRACK)
class BacktrackTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.BACKTRACK,
            type="function",
            description=load_desc(Path(__file__).parent / "backtrack_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "checkpoint_id": {
                        "type": "integer",
                        "description": "The checkpoint ID to revert to",
                    },
                    "note": {
                        "type": "string",
                        "description": "A note to your future self with key findings/context",
                    },
                    "rationale": {
                        "type": "string",
                        "description": "Why you are performing this backtrack",
                    },
                },
                "required": ["checkpoint_id", "note", "rationale"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = BacktrackArguments.model_validate_json(arguments)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")

        backtrack_manager = context.backtrack_manager
        if backtrack_manager is None:
            return message.ToolResultMessage(
                status="error",
                output_text="Backtrack is not available in this context",
            )

        try:
            result = backtrack_manager.send_backtrack(args.checkpoint_id, args.note, args.rationale)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        return message.ToolResultMessage(status="success", output_text=result)
