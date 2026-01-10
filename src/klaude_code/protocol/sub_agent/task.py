from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

TASK_SUMMARY = "General-purpose agent for researching complex questions, searching for code, and executing multi-step tasks. (Tools: All Tools)"

register_sub_agent(
    SubAgentProfile(
        name="Task",
        prompt_file="prompts/prompt-sub-agent.md",
        tool_set=(tools.BASH, tools.READ, tools.EDIT, tools.WRITE),
        invoker_type="general-purpose",
        invoker_summary=TASK_SUMMARY,
        active_form="Tasking",
    )
)
