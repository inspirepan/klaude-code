from typing import Literal

from pydantic import BaseModel

from klaude_code.core.tool.tool_abc import ToolABC
from klaude_code.core.tool.tool_context import current_run_subtask_callback
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol.llm_parameter import ToolSchema
from klaude_code.protocol.model import ToolResultItem
from klaude_code.protocol.tools import EXPLORE, SubAgentType


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
                'Spin up a fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), '
                'search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?")'
                'When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions'
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
                        "description": "The task for the agent to perform",
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
