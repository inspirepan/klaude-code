from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

GENERAL_PURPOSE_SUMMARY = (
    "Fire-and-forget executor for heavy, multi-file implementations. Think of it as a productive\n"
    "junior engineer who can't ask follow-ups once started.\n"
    "- Use for: Feature scaffolding, cross-layer refactors, mass migrations, boilerplate generation\n"
    "- Don't use for: Read-only research or search (use finder instead), architectural decisions\n"
    "- Prompt it with detailed instructions on the goal, enumerate the deliverables, give it step\n"
    "  by step procedures and ways to validate the results. Also give it constraints (e.g. coding\n"
    "  style) and include relevant context snippets or examples. (Tools: All Tools)"
)

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

FORK_CONTEXT_SUMMARY = (
    "Same as general-purpose but with full conversation history forked from the parent agent.\n"
    "Use when the sub-agent needs awareness of what happened earlier in the session.\n"
    "- Use for: Session-aware tasks like updating project docs, summarizing session learnings,\n"
    "  or any task that requires the full conversation context to do well\n"
    "- Don't use for: Standalone tasks that don't need session history (use general-purpose instead)\n"
    "(Tools: inherited from parent)"
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
