from typing import Literal

from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_run_subtask_callback
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import EXPLORE, SubAgentType


class ExploreArguments(BaseModel):
    description: str
    prompt: str
    thoroughness: Literal["quick", "medium", "very thorough"] = "medium"


@register(EXPLORE)
class ExploreTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=EXPLORE,
            type="function",
            description=(
                "Spin up a read-only exploration specialist to locate files, search code, and summarize findings. "
                "Use this whenever you need broader repository context, structured file searches, or need to trace how "
                "logic flows across multiple directories."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Short (3-5 words) label for the exploration goal",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Full instructions describing what to search for and what to report back",
                    },
                    "thoroughness": {
                        "type": "string",
                        "enum": ["quick", "medium", "very thorough"],
                        "description": "Controls how deep the sub-agent should search the repo",
                    },
                },
                "required": ["description", "prompt"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = ExploreArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        runner = current_run_subtask_callback.get()
        if runner is None:
            return ToolResultItem(status="error", output="No subtask runner available in this context")

        try:
            result = await runner(args.prompt.strip() + "\nthoroughness: " + args.thoroughness, SubAgentType.EXPLORE)
        except Exception as e:  # safeguard
            return ToolResultItem(status="error", output=f"Failed to run explore subtask: {e}")

        return ToolResultItem(
            status="success" if not result.error else "error",
            output=result.task_result or "",
            ui_extra=result.session_id,
        )
