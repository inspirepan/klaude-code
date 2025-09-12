from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_run_subtask_callback
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import ORACLE, SubAgentType


class OracleArguments(BaseModel):
    description: str
    prompt: str


@register(ORACLE)
class OracleTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=ORACLE,
            type="function",
            description=(
                """Consult the Oracle - an AI advisor powered by OpenAI's premium reasoning model that can plan, review, and provide expert guidance.

The Oracle has access to the following tools: Read, Bash.

The Oracle acts as your senior engineering advisor and can help with:

WHEN TO USE THE ORACLE:
- Code reviews and architecture feedback
- Finding a bug in multiple files
- Planning complex implementations or refactoring
- Analyzing code quality and suggesting improvements
- Answering complex technical questions that require deep reasoning

WHEN NOT TO USE THE ORACLE:
- Simple file reading or searching tasks (use Read or Grep directly)
- Codebase searches (use Task)
- Basic code modifications and when you need to execute code changes (do it yourself or use Task)

USAGE GUIDELINES:
1. Be specific about what you want the Oracle to review, plan, or debug
2. Provide relevant context about what you're trying to achieve. If you know that 3 files are involved, list them.
3. Use `@<file_path>` so the file content will automatically be attached to the prompt.


EXAMPLES:
- "Review the authentication system architecture and suggest improvements"
- "Plan the implementation of real-time collaboration features"
- "Analyze the performance bottlenecks in the data processing pipeline"
- "Review this API design and suggest better patterns"""
            ),
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "A short (3-5 word) description of the task",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The task for the agent to perform",
                    },
                },
                "required": ["description", "prompt"],
                "additionalProperties": False,
            },
        )

    @classmethod
    async def call(cls, arguments: str) -> ToolResultItem:
        try:
            args = OracleArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        runner = current_run_subtask_callback.get()
        if runner is None:
            return ToolResultItem(status="error", output="No subtask runner available in this context")

        try:
            result = await runner(args.prompt, SubAgentType.ORACLE)
        except Exception as e:  # safeguard
            return ToolResultItem(status="error", output=f"Failed to run subtask: {e}")

        # This session_id in ui_extra is for replay history
        return ToolResultItem(
            status="success" if not result.error else "error",
            output=result.task_result or "",
            ui_extra=result.session_id,
        )
