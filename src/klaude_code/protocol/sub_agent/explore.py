from __future__ import annotations

from typing import Any

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
"""

EXPLORE_PARAMETERS = {
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
        "output_format": {
            "type": "object",
            "description": "Optional JSON Schema for sub-agent structured output",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}


def _explore_prompt_builder(args: dict[str, Any]) -> str:
    """Build the Explore prompt from tool arguments."""
    prompt = args.get("prompt", "").strip()
    thoroughness = args.get("thoroughness", "medium")
    return f"{prompt}\nthoroughness: {thoroughness}"


register_sub_agent(
    SubAgentProfile(
        name="Explore",
        description=EXPLORE_DESCRIPTION,
        parameters=EXPLORE_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-explore.md",
        tool_set=(tools.BASH, tools.READ),
        prompt_builder=_explore_prompt_builder,
        active_form="Exploring",
        output_schema_arg="output_format",
    )
)
