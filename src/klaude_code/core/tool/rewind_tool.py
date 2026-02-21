from pathlib import Path

from pydantic import BaseModel, Field

from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools


class RewindArguments(BaseModel):
    checkpoint_id: int = Field(description="The checkpoint ID to revert to")
    note: str = Field(description="A note to your future self with key findings/context to preserve")
    rationale: str = Field(description="Why you are performing this rewind")


@register(tools.REWIND)
class RewindTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.REWIND,
            type="function",
            description=load_desc(Path(__file__).parent / "rewind_tool.md"),
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
                        "description": "Why you are performing this rewind",
                    },
                },
                "required": ["checkpoint_id", "note", "rationale"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = RewindArguments.model_validate_json(arguments)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=f"Invalid arguments: {exc}")

        rewind_manager = context.rewind_manager
        if rewind_manager is None:
            return message.ToolResultMessage(
                status="error",
                output_text="Rewind is not available in this context",
            )

        try:
            result = rewind_manager.send_rewind(args.checkpoint_id, args.note, args.rationale)
        except ValueError as exc:
            return message.ToolResultMessage(status="error", output_text=str(exc))

        return message.ToolResultMessage(status="success", output_text=result)
