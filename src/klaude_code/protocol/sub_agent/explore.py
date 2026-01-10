from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

EXPLORE_SUMMARY = (
    "Fast codebase exploration: find files by patterns, search for keywords, and summarize how things work.\n"
    "Always spawn multiple search agents in parallel to maximise speed. "
    "(Tools: Bash, Read)"
)

register_sub_agent(
    SubAgentProfile(
        name="Explore",
        prompt_file="prompts/prompt-sub-agent-explore.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_type="explore",
        invoker_summary=EXPLORE_SUMMARY,
        active_form="Exploring",
    )
)
