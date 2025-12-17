import asyncio
import json
import re
import time
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from pydantic import BaseModel

from klaude_code import const
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, model, tools

DEFAULT_TIMEOUT_SEC = 30
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; KlaudeCode/1.0)"
WEB_FETCH_SAVE_DIR = Path(const.TOOL_OUTPUT_TRUNCATION_DIR) / "web"


def _encode_url(url: str) -> str:
    """Encode non-ASCII characters in URL to make it safe for HTTP requests."""
    parsed = urlparse(url)
    encoded_path = quote(parsed.path, safe="/-_.~")
    encoded_query = quote(parsed.query, safe="=&-_.~")
    # Handle IDN (Internationalized Domain Names) by encoding to punycode
    try:
        netloc = parsed.netloc.encode("idna").decode("ascii")
    except UnicodeError:
        netloc = parsed.netloc
    return urlunparse((parsed.scheme, netloc, encoded_path, parsed.params, encoded_query, parsed.fragment))


def _extract_content_type_and_charset(response: HTTPResponse) -> tuple[str, str | None]:
    """Extract the base content type and charset from Content-Type header."""
    content_type_header = response.getheader("Content-Type", "")
    parts = content_type_header.split(";")
    content_type = parts[0].strip().lower()

    charset = None
    for part in parts[1:]:
        part = part.strip()
        if part.lower().startswith("charset="):
            charset = part[8:].strip().strip("\"'")
            break

    return content_type, charset


def _detect_encoding(data: bytes, declared_charset: str | None) -> str:
    """Detect the encoding of the data."""
    # 1. Use declared charset from HTTP header if available
    if declared_charset:
        return declared_charset

    # 2. Try to detect from HTML meta tags (check first 2KB)
    head = data[:2048].lower()
    # <meta charset="xxx">
    if match := re.search(rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', head):
        return match.group(1).decode("ascii", errors="ignore")
    # <meta http-equiv="Content-Type" content="text/html; charset=xxx">
    if match := re.search(rb'content=["\'][^"\']*charset=([^"\'\s;]+)', head):
        return match.group(1).decode("ascii", errors="ignore")

    # 3. Use chardet for automatic detection
    import chardet

    result = chardet.detect(data)
    if result["encoding"] and result["confidence"] and result["confidence"] > 0.7:
        return result["encoding"]

    # 4. Default to UTF-8
    return "utf-8"


def _decode_content(data: bytes, declared_charset: str | None) -> str:
    """Decode bytes to string with automatic encoding detection."""
    encoding = _detect_encoding(data, declared_charset)

    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        # Fallback: try UTF-8 with replacement for invalid chars
        return data.decode("utf-8", errors="replace")


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
    encoded_url = _encode_url(url)
    request = urllib.request.Request(encoded_url, headers=headers)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type, charset = _extract_content_type_and_charset(response)
        data = response.read()
        text = _decode_content(data, charset)
        return content_type, text


@register(tools.WEB_FETCH)
class WebFetchTool(ToolABC):
    @classmethod
    def metadata(cls) -> ToolMetadata:
        return ToolMetadata(concurrency_policy=ToolConcurrencyPolicy.CONCURRENT, has_side_effects=True)

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
                output=f"Invalid URL: must start with http:// or https:// (url={url})",
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
                output=f"HTTP error {e.code}: {e.reason} (url={url})",
            )
        except urllib.error.URLError as e:
            return model.ToolResultItem(
                status="error",
                output=f"URL error: {e.reason} (url={url})",
            )
        except TimeoutError:
            return model.ToolResultItem(
                status="error",
                output=f"Request timed out after {DEFAULT_TIMEOUT_SEC} seconds (url={url})",
            )
        except Exception as e:
            return model.ToolResultItem(
                status="error",
                output=f"Failed to fetch URL: {e} (url={url})",
            )
