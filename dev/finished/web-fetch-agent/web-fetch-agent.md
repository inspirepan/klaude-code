# WebFetch Tool and WebFetchAgent Design Document

## Overview

Implement a web content fetching capability with two components:
1. **WebFetch Tool**: Internal tool for fetching and processing web content (not exposed to main agent)
2. **WebFetchAgent**: Sub-agent that wraps WebFetch, exposed to main agent for web content analysis

## Architecture

```
Main Agent
    |
    v
WebFetchAgent (Sub-agent)
    |
    +-- Bash tool
    +-- Read tool  
    +-- WebFetch tool (internal, not in main agent)
```

## Component 1: WebFetch Tool

### Location
`src/klaude_code/core/tool/web_fetch_tool.py`

### Parameters
| Parameter | Type   | Required | Description |
|-----------|--------|----------|-------------|
| url       | string | Yes      | The URL to fetch |

### Processing Logic

1. **HTTP Request**
   - Use `httpx` or `aiohttp` for async HTTP requests
   - Set header: `Accept: text/markdown, */*`
   - Handle redirects, timeouts

2. **Response Validation**
   - Check HTTP status code (2xx = success)
   - Read response body
   - Validate UTF-8 encoding

3. **Content-Type Processing**
   | Content-Type | Processing |
   |--------------|------------|
   | `text/html` | Convert to Markdown using `trafilatura` |
   | `text/markdown` | Return as-is |
   | `application/json`, `text/json` | Format with indentation |
   | Others | Return raw content |

### Implementation Notes
- Tool name constant: `WEB_FETCH = "WebFetch"` in `protocol/tools.py`
- Register with `@register(WEB_FETCH)` but NOT added to main agent tools
- Will be included in WebFetchAgent's tool_set

## Component 2: WebFetchAgent Sub-agent

### Location
Registration in `src/klaude_code/core/sub_agent.py`

### Parameters (exposed to main agent)
| Parameter   | Type   | Required | Description |
|-------------|--------|----------|-------------|
| url         | string | Yes      | The URL to fetch and analyze |
| prompt      | string | Yes      | Instructions for analyzing/extracting content |
| description | string | Yes      | Short task description (3-5 words) |

### Tools Available to Sub-agent
- `Bash` - for using `rg` to search large saved files
- `Read` - for reading truncated content files
- `WebFetch` - for fetching web content

### Prompt Builder
Custom prompt builder that combines url and prompt:
```python
def _web_fetch_prompt_builder(args: dict[str, Any]) -> str:
    url = args.get("url", "")
    prompt = args.get("prompt", "")
    return f"URL to fetch: {url}\n\nTask: {prompt}"
```

### System Prompt
Location: `src/klaude_code/core/prompts/prompt-sub-agent-webfetch.md`

Content should include:
- Instructions for using WebFetch tool
- Handling of truncated outputs (use rg/Read for large files)
- Content extraction and analysis guidance

## File Changes Summary

### New Files
1. `src/klaude_code/core/tool/web_fetch_tool.py` - WebFetch tool implementation
2. `src/klaude_code/core/prompts/prompt-sub-agent-webfetch.md` - Sub-agent system prompt

### Modified Files
1. `src/klaude_code/protocol/tools.py` - Add `WEB_FETCH` constant
2. `src/klaude_code/core/tool/__init__.py` - Export WebFetchTool
3. `src/klaude_code/core/sub_agent.py` - Register WebFetchAgent
4. `src/klaude_code/core/prompt.py` - Add prompt file mapping
5. `pyproject.toml` - Add prompt file to build config

## Implementation Order

1. Add `WEB_FETCH` constant to `protocol/tools.py`
2. Create `web_fetch_tool.py` with WebFetch implementation
3. Update `tool/__init__.py` exports
4. Create `prompt-sub-agent-webfetch.md`
5. Add prompt mapping in `prompt.py`
6. Register WebFetchAgent in `sub_agent.py`
7. Update `pyproject.toml` build config

## Dependencies

- `trafilatura` - HTML to Markdown conversion (already added)
- `urllib.request` - Python stdlib HTTP client (no additional deps needed)

## Status

- [x] Design document
- [x] WebFetch tool implementation
- [x] WebFetchAgent registration
- [x] Prompt file
- [x] Build config update
- [ ] Testing
