import asyncio
import json
import re
import urllib.error
import urllib.request
from http.client import HTTPResponse
from pathlib import Path
from urllib.parse import quote, urlparse, urlunparse

from pydantic import BaseModel

from klaude_code.const import (
    TOOL_OUTPUT_TRUNCATION_DIR,
    URL_FILENAME_MAX_LENGTH,
    WEB_FETCH_DEFAULT_TIMEOUT_SEC,
    WEB_FETCH_USER_AGENT,
)
from klaude_code.core.tool.context import ToolContext
from klaude_code.core.tool.tool_abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.core.tool.tool_registry import register
from klaude_code.protocol import llm_param, message, tools

WEB_FETCH_SAVE_DIR = Path(TOOL_OUTPUT_TRUNCATION_DIR)


def _encode_url(url: str) -> str:
    """Encode non-ASCII characters in URL to make it safe for HTTP requests."""
    parsed = urlparse(url)
    encoded_path = quote(parsed.path, safe="/-_.~")
    encoded_query = quote(parsed.query, safe="=&-_.~")
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
    if declared_charset:
        return declared_charset

    head = data[:2048].lower()
    if match := re.search(rb'<meta[^>]+charset=["\']?([^"\'\s>]+)', head):
        return match.group(1).decode("ascii", errors="ignore")
    if match := re.search(rb'content=["\'][^"\']*charset=([^"\'\s;]+)', head):
        return match.group(1).decode("ascii", errors="ignore")

    import chardet

    result = chardet.detect(data)
    if result["encoding"] and result["confidence"] and result["confidence"] > 0.7:
        return result["encoding"]

    return "utf-8"


def _decode_content(data: bytes, declared_charset: str | None) -> str:
    """Decode bytes to string with automatic encoding detection."""
    encoding = _detect_encoding(data, declared_charset)
    try:
        return data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
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
    return name[:URL_FILENAME_MAX_LENGTH] if len(name) > URL_FILENAME_MAX_LENGTH else name


def _save_binary_content(url: str, data: bytes, extension: str = ".bin") -> str | None:
    """Save binary content to file. Returns file path or None on failure."""
    try:
        WEB_FETCH_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        identifier = _extract_url_filename(url)
        filename = f"klaude-webfetch-{identifier}{extension}"
        file_path = WEB_FETCH_SAVE_DIR / filename
        file_path.write_bytes(data)
        return str(file_path)
    except OSError:
        return None


def _save_text_content(url: str, content: str) -> str | None:
    """Save text content to file. Returns file path or None on failure."""
    try:
        WEB_FETCH_SAVE_DIR.mkdir(parents=True, exist_ok=True)
        identifier = _extract_url_filename(url)
        filename = f"klaude-webfetch-{identifier}.txt"
        file_path = WEB_FETCH_SAVE_DIR / filename
        file_path.write_text(content, encoding="utf-8")
        return str(file_path)
    except OSError:
        return None


def _is_pdf_url(url: str) -> bool:
    """Check if URL points to a PDF file."""
    parsed = urlparse(url)
    return parsed.path.lower().endswith(".pdf") or "/pdf/" in parsed.path.lower()


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


def _fetch_url(url: str, timeout: int = WEB_FETCH_DEFAULT_TIMEOUT_SEC) -> tuple[str, bytes, str | None]:
    """Fetch URL content synchronously."""
    headers = {
        "Accept": "text/markdown, */*",
        "User-Agent": WEB_FETCH_USER_AGENT,
    }
    encoded_url = _encode_url(url)
    request = urllib.request.Request(encoded_url, headers=headers)

    with urllib.request.urlopen(request, timeout=timeout) as response:
        content_type, charset = _extract_content_type_and_charset(response)
        data = response.read()
        return content_type, data, charset


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
    async def call(cls, arguments: str, context: ToolContext) -> message.ToolResultMessage:
        try:
            args = WebFetchTool.WebFetchArguments.model_validate_json(arguments)
        except ValueError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Invalid arguments: {e}",
            )
        return await cls.call_with_args(args, context)

    @classmethod
    async def call_with_args(cls, args: WebFetchArguments, context: ToolContext) -> message.ToolResultMessage:
        del context
        url = args.url

        if not url.startswith(("http://", "https://")):
            return message.ToolResultMessage(
                status="error",
                output_text=f"Invalid URL: must start with http:// or https:// (url={url})",
            )

        try:
            content_type, data, charset = await asyncio.to_thread(_fetch_url, url)

            # Handle PDF files - must save binary content
            if content_type == "application/pdf" or _is_pdf_url(url):
                saved_path = _save_binary_content(url, data, ".pdf")
                if saved_path:
                    return message.ToolResultMessage(
                        status="success",
                        output_text=f"PDF file saved to: {saved_path}\n\nTo read the PDF content, use the Read tool on this file path.",
                    )
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"Failed to save PDF file (url={url})",
                )

            # Handle text content - save to file and return with path hint
            text = _decode_content(data, charset)
            processed = _process_content(content_type, text)
            saved_path = _save_text_content(url, processed)
            output = f"[Web content saved to {saved_path}]\n\n{processed}" if saved_path else processed

            return message.ToolResultMessage(
                status="success",
                output_text=output,
            )

        except urllib.error.HTTPError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"HTTP error {e.code}: {e.reason} (url={url})",
            )
        except urllib.error.URLError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"URL error: {e.reason} (url={url})",
            )
        except TimeoutError:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Request timed out after {WEB_FETCH_DEFAULT_TIMEOUT_SEC} seconds (url={url})",
            )
        except Exception as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Failed to fetch URL: {e} (url={url})",
            )
