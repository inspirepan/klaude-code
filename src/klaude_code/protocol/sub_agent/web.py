from __future__ import annotations

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

WEB_SUMMARY = (
    "Web research: search, fetch, and analyze pages for up-to-date info; summarize findings with sources. "
    "Include dates in queries when recency matters. "
    "(Tools: WebSearch, WebFetch, Bash, Read, Write)"
)

register_sub_agent(
    SubAgentProfile(
        name="Web",
        prompt_file="prompts/prompt-sub-agent-web.md",
        tool_set=(tools.BASH, tools.READ, tools.WEB_FETCH, tools.WEB_SEARCH, tools.WRITE),
        invoker_type="web",
        invoker_summary=WEB_SUMMARY,
        active_form="Surfing",
    )
)
