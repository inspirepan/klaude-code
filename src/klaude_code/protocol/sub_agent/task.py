from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

TASK_DESCRIPTION = """\
Launch a new agent to handle complex, multi-step tasks autonomously. \

When NOT to use the Task tool:
- If you want to read a specific file path, use the Read or Bash tool for `rg` instead of the Task tool, to find the match more quickly
- If you are searching for a specific class definition like "class Foo", use the Bash tool for `rg` instead, to find the match more quickly
- If you are searching for code within a specific file or set of 2-3 files, use the Read tool instead of the Task tool, to find the match more quickly
- Other tasks that are not related to the agent descriptions above

Usage notes:
- Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
- When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.
- Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.
- The agent's outputs should generally be trusted
- Clearly tell the agent whether you expect it to write code or just to do research (search, file reads, etc.), since it is not aware of the user's intent
- If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
- If the user specifies that they want you to run agents "in parallel", you MUST send a single message with multiple Task tool use content blocks. For example, if you need to launch both a code-reviewer agent and a test-runner agent in parallel, send a single message with both tool calls.

Structured output:
- Provide an `output_format` (JSON Schema) parameter for structured data back from the agent
- Example: `output_format={"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}, "description": "List of file paths that match the search criteria, e.g. ['src/main.py', 'src/utils/helper.py']"}}, "required": ["files"]}`\
"""

TASK_PARAMETERS = {
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
        "output_format": {
            "type": "object",
            "description": (
                "Optional JSON Schema for structured output, better with examples in argument descriptions."
            ),
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}

register_sub_agent(
    SubAgentProfile(
        name="Task",
        description=TASK_DESCRIPTION,
        parameters=TASK_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent.md",
        tool_set=(tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.MOVE),
        active_form="Tasking",
        output_schema_arg="output_format",
    )
)
