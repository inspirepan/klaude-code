from pydantic import BaseModel

from codex_mini.core.tool.tool_abc import ToolABC
from codex_mini.core.tool.tool_context import current_run_subtask_callback
from codex_mini.core.tool.tool_registry import register
from codex_mini.protocol.llm_parameter import ToolSchema
from codex_mini.protocol.model import ToolResultItem
from codex_mini.protocol.tools import TASK, SubAgentType


class TaskArguments(BaseModel):
    description: str
    prompt: str


@register(TASK)
class TaskTool(ToolABC):
    @classmethod
    def schema(cls) -> ToolSchema:
        return ToolSchema(
            name=TASK,
            type="function",
            description=(
                "Launch a new agent to handle complex, multi-step tasks autonomously. "
                "\n"
                "When to use the Task tool:\n"
                '- If you are searching for a keyword like "config" or "logger", or for questions like "which file does X?", the Task tool is strongly recommended\n'
                "\n"
                "When NOT to use the Task tool:\n"
                "- If you want to read a specific file path, use the Read or Bash tool for `rg` instead of the Agent tool, to find the match more quickly\n"
                '- If you are searching for a specific class definition like "class Foo", use the Bash tool for `rg` instead, to find the match more quickly\n'
                "- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead of the Agent tool, to find the match more quickly\n"
                "- Other tasks that are not related to the agent descriptions above\n"
                "\n"
                "Usage notes:\n"
                "1. Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses\n"
                "2. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.\n"
                "3. Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.\n"
                "4. The agent's outputs should generally be trusted\n"
                "5. Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, etc.), since it is not aware of the user's intent\n"
                "6. If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.\n"
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
            args = TaskArguments.model_validate_json(arguments)
        except ValueError as e:
            return ToolResultItem(status="error", output=f"Invalid arguments: {e}")

        runner = current_run_subtask_callback.get()
        if runner is None:
            return ToolResultItem(status="error", output="No subtask runner available in this context")

        try:
            result = await runner(args.prompt, SubAgentType.TASK)
        except Exception as e:  # safeguard
            return ToolResultItem(status="error", output=f"Failed to run subtask: {e}")

        # This session_id in ui_extra is for replay history
        return ToolResultItem(
            status="success" if not result.error else "error",
            output=result.task_result or "",
            ui_extra=result.session_id,
        )
