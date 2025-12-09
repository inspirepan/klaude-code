from __future__ import annotations

from typing import Any

from klaude_code.protocol import tools
from klaude_code.protocol.sub_agent import SubAgentProfile, register_sub_agent

WEB_FETCH_AGENT_DESCRIPTION = """\
Launch a sub-agent to fetch and analyze web content. Use this when you need to:
- Retrieve and extract information from a webpage
- Analyze web page content based on specific instructions
- Get structured data from URLs

This is an autonomous agent with its own reasoning capabilities. It can:
- Follow links and navigate across multiple pages to gather comprehensive information
- Decide which related pages to visit based on the initial content
- Aggregate information from multiple sources into a coherent response

The agent will fetch the URL content, handle HTML-to-Markdown conversion automatically, \
and can use tools like rg to search through large responses that were truncated and saved to files.

Usage notes:
- Provide a clear prompt describing what information to extract or analyze
- The agent will return a summary of the findings
- For large web pages, the content may be truncated and saved to a file; the agent can search through it
- The agent can autonomously follow links to related pages if needed to complete the task\
"""

WEB_FETCH_AGENT_PARAMETERS = {
    "type": "object",
    "properties": {
        "description": {
            "type": "string",
            "description": "A short (3-5 word) description of the task",
        },
        "url": {
            "type": "string",
            "description": "The URL to fetch and analyze",
        },
        "prompt": {
            "type": "string",
            "description": "Instructions for analyzing or extracting content from the web page",
        },
    },
    "required": ["description", "url", "prompt"],
    "additionalProperties": False,
}


def _web_fetch_prompt_builder(args: dict[str, Any]) -> str:
    """Build the WebFetchAgent prompt from tool arguments."""
    url = args.get("url", "")
    prompt = args.get("prompt", "")
    return f"URL to fetch: {url}\nTask: {prompt}"


register_sub_agent(
    SubAgentProfile(
        name="WebFetchAgent",
        description=WEB_FETCH_AGENT_DESCRIPTION,
        parameters=WEB_FETCH_AGENT_PARAMETERS,
        prompt_file="prompts/prompt-sub-agent-webfetch.md",
        tool_set=(tools.BASH, tools.READ, tools.WEB_FETCH),
        prompt_builder=_web_fetch_prompt_builder,
        active_form="Fetching Web",
    )
)
