import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool.tool_abc import ToolABC, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; KlaudeCode/1.0)"
WEB_FETCH_SAVE_DIR = Path(const.TOOL_OUTPUT_TRUNCATION_DIR) / "web"


def _extract_content_type(response: HTTPResponse) -> str:
    """Extract the base content type without charset parameters."""
    content_type = response.getheader("Content-Type", "")
    return content_type.split(";")[0].strip().lower()


def _validate_utf8(data: bytes) -> str:
    """Validate and decode bytes as UTF-8."""
    return data.decode("utf-8")


def _convert_html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown using trafilatura."""
    import trafilatura

    result = trafilatura.extract(html, output_format="markdown", include_links=True, include_images=True)
    return result or ""


def _format_json(text: str) -> str:
    """Format JSON with indentation."""
    try:
        parsed = json.loads(text)
        return json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return text


def _extract_url_filename(url: str) -> str:
    """Extract a safe filename from a URL."""
    parsed = urlparse(url)
    host = parsed.netloc.replace(".", "_").replace(":", "_")
    path = parsed.path.strip("/").replace("/", "_")
    name = f"{host}_{path}" if path else host
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    return name[:80] if len(name) > 80 else name


def _save_web_content(url: str, content: str) -> str | None:
    """Save web content to file. Returns file path or None on failure."""
    try:
        WEB_FETCH_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        identifier = _extract_url_filename(url)
        filename = f"{identifier}-{timestamp}.md"
        file_path = WEB_FETCH_SAVE_DIR / filename
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)
    except OSError:
        return None


def _process_content(content_type: str, text: str) -> str:
    """Process content based on Content-Type header."""
    if content_type == "text/html":
        return _convert_html_to_markdown(text)
    elif content_type == "text/markdown":
        return text
    elif content_type in ("application/json", "text/json"):
        return _format_json(text)
    else:
        return text


def _fetch_url(url: str, timeout: int = DEFAULT_TIMEOUT_SEC) -> tuple[str, str]:
    """
    Fetch URL content synchronously.

    Returns:
        Tuple of (content_type, response_text)

    Raises:
        Various exceptions on failure
    """
    headers = {
        "Accept": "text/markdown, */*",
        "User-Agent": DEFAULT_USER_AGENT,
    }
    request = urllib.request.Request(url, headers=headers)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type = _extract_content_type(response)
        data = response.read()
        text = _validate_utf8(data)
        return content_type, text


@register(tools.WEB_FETCH)
class WebFetchTool(ToolABC):
    @classmethod
    def schema(cls) -> llm_param.ToolSchema:
        return llm_param.ToolSchema(
            name=tools.WEB_FETCH,
            type="function",
            description=load_desc(Path(__file__).parent / "web_fetch_tool.md"),
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch",
                    },
                },
                "required": ["url"],
            },
        )

    class WebFetchArguments(BaseModel):
        url: str

    @classmethod
    async def call(cls, arguments: str) -> model.ToolResultItem:
        try:
            args = WebFetchTool.WebFetchArguments.model_validate_json(arguments)
        except ValueError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args)

    @classmethod
    async def call_with_args(cls, args: WebFetchArguments) -> model.ToolResultItem:
        url = args.url

        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            return model.ToolResultItem(
                status="error",
                output="Invalid URL: must start with http:// or https://",
            )

        try:
            content_type, text = await asyncio.to_thread(_fetch_url, url)
            processed = _process_content(content_type, text)

            # Always save content to file
            saved_path = _save_web_content(url, processed)

            # Build output with file path info
            output = f"<file_saved>{saved_path}</file_saved>\n\n{processed}" if saved_path else processed

            return model.ToolResultItem(
                status="success",
                output=output,
            )

        except urllib.error.HTTPError as e:
            return model.ToolResultItem(
                status="error",
                output=f"HTTP error {e.code}: {e.reason}",
            )
        except urllib.error.URLError as e:
            return model.ToolResultItem(
                status="error",
                output=f"URL error: {e.reason}",
            )
        except UnicodeDecodeError as e:
            return model.ToolResultItem(
                status="error",
                output=f"Content is not valid UTF-8: {e}",
            )
        except TimeoutError:
            return model.ToolResultItem(
                status="error",
                output=f"Request timed out after {DEFAULT_TIMEOUT_SEC} seconds",
            )
        except Exception as e:
            return model.ToolResultItem(
                status="error",
                output=f"Failed to fetch URL: {e}",
            )
