from __future__ import annotations

from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

MEMORY_SUMMARY = (
    "Session-aware agent that updates project memory files (AGENTS.md) with learnings from\n"
    "the current session. Inherits full conversation context via fork.\n"
    "- Use for: Capturing session learnings, auditing AGENTS.md quality, updating project docs\n"
    "  with discovered commands, gotchas, patterns, and architecture knowledge\n"
    "- Don't use for: General file editing or code changes\n"
    "- The agent reflects on the session, finds AGENTS.md files, and makes targeted updates.\n"
    "  It inherits the full conversation history so it knows what was learned.\n"
    "(Tools: inherited from parent)"
)

register_sub_agent(
    SubAgentProfile(
        name="memory",
        prompt_file="prompts/prompt-sub-agent-memory.md",
        fork_context=True,
        invoker_summary=MEMORY_SUMMARY,
        active_form="Updating memory",
    )
)
