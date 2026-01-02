from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

EXPLORE_DESCRIPTION = """\
Spin up a fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), \
search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?")\
When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions.
Always spawn multiple search agents in parallel to maximise speed.

Structured output:
- Provide an `output_format` (JSON Schema) parameter for structured data back from the sub-agent
- Example: `output_format={"type": "object", "properties": {"files": {"type": "array", "items": {"type": "string"}, "description": "List of file paths that match the search criteria, e.g. ['src/main.py', 'src/utils/helper.py']"}}, "required": ["files"]}`\

- Agents can be resumed using the `resume` parameter by passing the agent ID from a previous invocation. When resumed, the agent
continues with its full previous context preserved. When NOT resuming, each invocation starts fresh and you should provide a detailed
task description with all necessary context.
- When the agent is done, it will return a single message back to you along with its agent ID. You can use this ID to resume the agent
later if needed for follow-up work.
"""

EXPLORE_PARAMETERS = {
    "type": "object",
    "properties": {
        "resume": {
            "type": "string",
            "description": "Optional agent ID to resume from. If provided, the agent will continue from the previous execution transcript.",
        },
        "description": {
            "type": "string",
            "description": "Short (3-5 words) label for the exploration goal",
        },
        "prompt": {
            "type": "string",
            "description": "The task for the agent to perform",
        },
        "output_format": {
            "type": "object",
            "description": "Optional JSON Schema for sub-agent structured output",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}


register_sub_agent(
    SubAgentProfile(
        name="Explore",
        description=EXPLORE_DESCRIPTION,
        parameters=EXPLORE_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-explore.md",
        tool_set=(tools.BASH, tools.READ),
        active_form="Exploring",
        output_schema_arg="output_format",
    )
)
