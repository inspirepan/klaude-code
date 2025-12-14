from __future__ import annotations

from typing import Any

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

WEB_AGENT_DESCRIPTION = """\
Launch a sub-agent to search the web, fetch pages, and analyze content. Use this for:
- Accessing up-to-date information beyond your knowledge cutoff (current events, recent releases, latest docs)
- Researching topics, news, APIs, or technical references
- Fetching and analyzing specific URLs
- Gathering comprehensive information from multiple web sources

Capabilities:
- Search the web to find relevant pages (no URL required)
- Fetch and parse web pages (HTML-to-Markdown conversion)
- Follow links across multiple pages autonomously
- Aggregate findings from multiple sources

How to use:
- Write a clear prompt describing what information you need - the agent will search and fetch as needed
- Account for "Today's date" in <env>. For example, if <env> says "Today's date: 2025-07-01", and the user wants the latest docs, do not use 2024 in the search query. Use 2025.
- Optionally provide a `url` if you already know the target page
- Use `output_format` (JSON Schema) to get structured data back from the agent

What you receive:
- The agent returns a text response summarizing its findings
- With `output_format`, you receive structured JSON matching your schema
- The response is the agent's analysis, not raw web content
- Web content is saved to local files (paths included in Sources) - read them directly if you need full content\
"""

WEB_AGENT_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "url": {
            "type": "string",
            "description": "The URL to fetch and analyze. If not provided, the agent will search the web first",
        },
        "prompt": {
            "type": "string",
            "description": "Instructions for searching, analyzing, or extracting content from the web page",
        },
        "output_format": {
            "type": "object",
            "description": "Optional JSON Schema for sub-agent structured output",
        },
    },
    "required": ["description", "prompt"],
    "additionalProperties": False,
}


def _web_agent_prompt_builder(args: dict[str, Any]) -> str:
    """Build the WebAgent prompt from tool arguments."""
    url = args.get("url", "")
    prompt = args.get("prompt", "")
    if url:
        return f"URL to fetch: {url}\nTask: {prompt}"
    return prompt


register_sub_agent(
    SubAgentProfile(
        name="WebAgent",
        description=WEB_AGENT_DESCRIPTION,
        parameters=WEB_AGENT_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-web.md",
        tool_set=(tools.BASH, tools.READ, tools.WEB_FETCH, tools.WEB_SEARCH, tools.WRITE),
        prompt_builder=_web_agent_prompt_builder,
        active_form="Surfing",
        output_schema_arg="output_format",
    )
)
