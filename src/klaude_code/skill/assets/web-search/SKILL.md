---
name: web-search
description: Search the web for up-to-date information and research topics. Use this skill when the user asks to search, look up, find current info, research a topic, or needs information beyond the knowledge cutoff. Triggers include "search", "look up", "web search", "find out", "what is the latest", "current status of".
---

Search the web and synthesize findings into concise, sourced answers.

## Tools

- **WebSearch**: Query the web. Returns title, URL, snippet per result. Use `max_results` (default 10, max 20).
- **WebFetch**: Fetch full page content. HTML auto-converts to Markdown. Full content saved to temp local file (path shown in output).

## Search Strategy

Scale tool calls to complexity:
- Simple facts: 1-2 calls
- Medium research: 3-5 calls
- Deep research/comparisons: 5-10 calls

### Query Construction

- Keep queries concise (1-6 words). Start broad, then narrow.
- Never repeat similar queries -- they yield the same results.
- Never use `-`, `site:`, or quotes unless the user explicitly asks.
- Include year/date for time-sensitive queries (check "Today's date" in `<env>`).

### Research Flow

1. Start with multiple targeted searches in parallel. Never rely on a single query.
2. Begin broad enough to capture the main answer, then add targeted follow-ups to fill gaps.
3. Always use WebFetch for complete content -- search snippets are often insufficient.
4. If fetched content is truncated and saved to a local file, use grep/read to explore.
5. Keep iterating until additional searching is unlikely to change the answer materially.

### Handling Ambiguity

Do not ask clarifying questions if acting as a sub-agent. State the interpretation plainly, then cover all plausible intents.

## Response Format

- Lead with the most recent info for evolving topics.
- Provide a concise summary of key findings. Do not copy full web page content.
- Favor original sources (company blogs, papers, gov sites) over aggregators.

### Sources (REQUIRED)

MUST end every response with a "Sources:" section listing all referenced URLs:

```
Sources:
- [Source Title 1](https://example.com/1)
- [Source Title 2](https://example.com/2)
```

## Completion Checklist

Stop only when all are true:
1. Answered the query and every subpart.
2. Found sufficient sources for core claims.
3. Resolved any contradictions between sources.
