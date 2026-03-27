from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

FINDER_SUMMARY = (
    "Intelligently search your codebase: use it for complex, multi-step search tasks where you\n"
    "need to find code based on functionality or concepts rather than exact matches. Anytime you\n"
    "want to chain multiple grep calls you should use this tool.\n"
    "Always spawn multiple search agents in parallel to maximise speed.\n"
    "The prompt must include:\n"
    "- objective: a natural-language description of the broader task or research goal\n"
    "- search_queries: keyword queries to prioritize specific term matches\n"
    "(Tools: Bash, Read)"
)

register_sub_agent(
    SubAgentProfile(
        name="Finder",
        prompt_file="prompts/prompt-sub-agent-finder.md",
        tool_set=(tools.BASH, tools.READ),
        invoker_type="finder",
        invoker_summary=FINDER_SUMMARY,
        active_form="Finding",
    )
)
