from pydantic import BaseModel, Field

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_run_subtask_callback
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import ORACLE, SubAgentType


class OracleArguments(BaseModel):
    context: str = Field(default="")
    files: list[str] = Field(default_factory=list)
    task: str
    description: str = Field(default="")


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
2. Provide relevant context about what you're trying to achieve. If you know that any files are involved, list them and they will be attached.


EXAMPLES:
- "Review the authentication system architecture and suggest improvements"
- "Plan the implementation of real-time collaboration features"
- "Analyze the performance bottlenecks in the data processing pipeline"
- "Review this API design and suggest better patterns"""
            ),
            parameters={
                "properties": {
                    "context": {
                        "description": "Optional context about the current situation, what you've tried, or background information that would help the Oracle provide better guidance.",
                        "type": "string",
                    },
                    "files": {
                        "description": "Optional list of specific file paths (text files, images) that the Oracle should examine as part of its analysis. These files will be attached to the Oracle input.",
                        "items": {"type": "string"},
                        "type": "array",
                    },
                    "task": {
                        "description": "The task or question you want the Oracle to help with. Be specific about what kind of guidance, review, or planning you need.",
                        "type": "string",
                    },
                    "description": {
                        "description": "A short (3-5 word) description of the task",
                        "type": "string",
                    },
                },
                "required": ["task", "description"],
                "type": "object",
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

        prompt = f"""Context: {args.context}

Task: {args.task}
"""
        if len(args.files) > 0:
            files_str = "\n".join(f"@{file}" for file in args.files)
            prompt += f"\nRelated files to review:\n{files_str}"

        try:
            result = await runner(prompt, SubAgentType.ORACLE)
        except Exception as e:  # safeguard
            return ToolResultItem(status="error", output=f"Failed to run subtask: {e}")

        # This session_id in ui_extra is for replay history
        return ToolResultItem(
            status="success" if not result.error else "error",
            output=result.task_result or "",
            ui_extra=result.session_id,
        )
