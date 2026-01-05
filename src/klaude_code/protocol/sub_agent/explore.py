from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

EXPLORE_DESCRIPTION = """\
Spin up a fast agent specialized for exploring codebases. Use this when you need to quickly find files by patterns (eg. "src/components/**/*.tsx"), \
search code for keywords (eg. "API endpoints"), or answer questions about the codebase (eg. "how do API endpoints work?")\
When calling this agent, specify the desired thoroughness level: "quick" for basic searches, "medium" for moderate exploration, or "very thorough" for comprehensive analysis across multiple locations and naming conventions.
Always spawn multiple search agents in parallel to maximise speed.
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
