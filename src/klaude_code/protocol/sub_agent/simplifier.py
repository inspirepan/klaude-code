from __future__ import annotations

from klaude_code.prompts.sub_agents import SIMPLIFIER_SUMMARY
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

register_sub_agent(
    SubAgentProfile(
        name="code-simplifier",
        prompt_file="prompts/sub_agents/prompt-sub-agent-simplifier.md",
        tool_set=(tools.BASH, tools.READ, tools.EDIT),
        invoker_summary=SIMPLIFIER_SUMMARY,
        active_form="Simplifying",
    )
)
