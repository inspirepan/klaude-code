from __future__ import annotations

from klaude_code.prompts.sub_agents import FORK_CONTEXT_SUMMARY, GENERAL_PURPOSE_SUMMARY
from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

register_sub_agent(
    SubAgentProfile(
        name="general-purpose",
        tool_set=(
            tools.BASH,
            tools.READ,
            tools.EDIT,
            tools.WRITE,
            tools.WEB_FETCH,
            tools.WEB_SEARCH,
            tools.ASK_USER_QUESTION,
        ),
        invoker_summary=GENERAL_PURPOSE_SUMMARY,
        use_main_prompt=True,
        active_form="Tasking",
    )
)

register_sub_agent(
    SubAgentProfile(
        name="general-purpose-fork-context",
        invoker_summary=FORK_CONTEXT_SUMMARY,
        use_main_prompt=True,
        fork_context=True,
        active_form="Tasking",
    )
)
