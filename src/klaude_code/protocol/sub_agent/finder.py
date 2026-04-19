from __future__ import annotations

from klaude_code.prompts.sub_agents import FINDER_SUMMARY
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

register_sub_agent(
    SubAgentProfile(
        name="finder",
        prompt_file="prompts/sub_agents/prompt-sub-agent-finder.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_summary=FINDER_SUMMARY,
        active_form="Finding",
    )
)
