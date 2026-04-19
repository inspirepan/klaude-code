from __future__ import annotations

from klaude_code.prompts.sub_agents import REVIEW_SUMMARY
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

register_sub_agent(
    SubAgentProfile(
        name="code-reviewer",
        prompt_file="prompts/sub_agents/prompt-sub-agent-review.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_summary=REVIEW_SUMMARY,
        active_form="Reviewing",
    )
)
