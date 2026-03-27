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
        name="Task",
        tool_set=(tools.BASH, tools.READ, tools.EDIT, tools.WRITE, tools.WEB_FETCH, tools.WEB_SEARCH),
        invoker_type="general-purpose",
        invoker_summary=GENERAL_PURPOSE_SUMMARY,
        use_main_prompt=True,
        active_form="Tasking",
    )
)
