from __future__ import annotations

from klaude_code.prompts.sub_agents import MAINTENANCE_REVIEW_SUMMARY
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

register_sub_agent(
    SubAgentProfile(
        name="code-maintenance-reviewer",
        prompt_file="prompts/sub_agents/prompt-sub-agent-maintenance-review.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_summary=MAINTENANCE_REVIEW_SUMMARY,
        active_form="Reviewing",
    )
)
