import asyncio
import gzip as gzip_module
import http.cookiejar
import json
import re
import time
import urllib.error
import urllib.request
import zlib
from http.client import HTTPMessage, HTTPResponse
from pathlib import Path
from typing import IO, cast
from urllib.parse import quote, urljoin, urlparse, urlunparse

from pydantic import BaseModel

from klaude_code.const import (
    TOOL_OUTPUT_TRUNCATION_DIR,
    URL_FILENAME_MAX_LENGTH,
    WEB_FETCH_DEFAULT_TIMEOUT_SEC,
    WEB_FETCH_MAX_REDIRECTS,
    WEB_FETCH_MAX_RESPONSE_BYTES,
    WEB_FETCH_USER_AGENT,
)
from klaude_code.protocol import llm_param, message, tools
from klaude_code.tool.core.abc import ToolABC, ToolConcurrencyPolicy, ToolMetadata, load_desc
from klaude_code.tool.core.context import ToolContext
from klaude_code.tool.core.registry import register
from klaude_code.tool.web.external_content import wrap_web_content
from klaude_code.tool.web.ssrf import SSRFBlockedError, check_ssrf
from klaude_code.tool.web.web_cache import get_cached, make_cache_key, set_cached

WEB_FETCH_SAVE_DIR = Path(TOOL_OUTPUT_TRUNCATION_DIR)

# Skip readability+trafilatura for HTML larger than 3MB to avoid excessive memory/CPU usage.
_READABILITY_MAX_HTML_CHARS = 3_000_000

# HTTP status codes that warrant a retry (transient server errors).
_RETRY_HTTP_STATUS_CODES = frozenset({500, 502, 503, 504})
_MAX_FETCH_RETRIES = 2


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Suppress automatic redirects so we can check each hop for SSRF."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        del req, fp, code, msg, headers, newurl
        return None


def _build_opener() -> urllib.request.OpenerDirector:
    """Build opener with manual redirect handling and per-request cookie jar."""
    cookie_jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookie_jar), _NoRedirectHandler)


def _encode_url(url: str) -> str:
    """Encode non-ASCII characters in URL to make it safe for HTTP requests."""
    parsed = urlparse(url)
    encoded_path = quote(parsed.path, safe="/%-_.~")
    encoded_query = quote(parsed.query, safe="=&/%:+?-_.~")
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


def _decompress(data: bytes, content_encoding: str) -> bytes:
    """Decompress response body based on Content-Encoding header."""
    encoding = content_encoding.strip().lower()
    if encoding == "gzip":
        try:
            return gzip_module.decompress(data)
        except (OSError, EOFError):
            return data
    elif encoding == "deflate":
        try:
            return zlib.decompress(data)
        except zlib.error:
            try:
                # Some servers send raw deflate without the zlib wrapper
                return zlib.decompress(data, -zlib.MAX_WBITS)
            except zlib.error:
                return data
    return data


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


def _strip_noise_elements(html: str) -> str:
    """Remove script and style elements to reduce size and noise before extraction."""
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    return html


def _html_to_markdown_fallback(html: str) -> str:
    """Simple regex-based HTML to text conversion as a fallback."""
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</(p|div|h[1-6]|li|tr|blockquote)>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"&lt;", "<", text)
    text = re.sub(r"&gt;", ">", text)
    text = re.sub(r"&quot;", '"', text)
    text = re.sub(r"&#39;", "'", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _convert_html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown using readability-lxml + trafilatura, with fallback."""
    # Strip scripts/styles first — main source of bulk with no content value
    stripped = _strip_noise_elements(html)

    if len(stripped) > _READABILITY_MAX_HTML_CHARS:
        return _html_to_markdown_fallback(stripped)

    # Strategy 1: readability-lxml isolates the article, then trafilatura converts to Markdown.
    # This combination handles sites with heavy navigation/footer noise (e.g. WeChat articles).
    try:
        from readability import Document  # type: ignore[import-untyped]

        doc = Document(stripped)
        article_html = cast(str, doc.summary())
        if article_html:
            import trafilatura

            result = trafilatura.extract(
                article_html, output_format="markdown", include_links=True, include_images=True
            )
            if result and len(result.strip()) > 50:
                return result
    except Exception:
        pass

    # Strategy 2: trafilatura directly on the stripped HTML
    import trafilatura

    result = trafilatura.extract(stripped, output_format="markdown", include_links=True, include_images=True)
    if result:
        return result

    return _html_to_markdown_fallback(stripped)


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
    return name[:URL_FILENAME_MAX_LENGTH]


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


def _fetch_url(
    url: str,
    timeout: int = WEB_FETCH_DEFAULT_TIMEOUT_SEC,
    max_bytes: int = WEB_FETCH_MAX_RESPONSE_BYTES,
    max_redirects: int = WEB_FETCH_MAX_REDIRECTS,
) -> tuple[str, bytes, str | None]:
    """Fetch URL content with SSRF protection and redirect control."""
    current_url = url
    opener = _build_opener()
    redirect_status_codes = (301, 302, 303, 307, 308)

    for _ in range(max_redirects + 1):
        check_ssrf(current_url)

        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "User-Agent": WEB_FETCH_USER_AGENT,
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Upgrade-Insecure-Requests": "1",
        }
        encoded_url = _encode_url(current_url)
        request = urllib.request.Request(encoded_url, headers=headers)

        try:
            response = opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code in redirect_status_codes:
                location = e.headers.get("Location")
                if not location:
                    raise urllib.error.URLError("Redirect without Location header") from e
                # Resolve relative redirects
                current_url = urljoin(current_url, location)
                e.close()
                continue
            raise

        if response.status in redirect_status_codes:
            location = response.getheader("Location")
            if not location:
                raise urllib.error.URLError("Redirect without Location header")
            # Resolve relative redirects
            current_url = urljoin(current_url, location)
            response.close()
            continue

        content_type, charset = _extract_content_type_and_charset(response)
        content_encoding = response.getheader("Content-Encoding", "")
        data = response.read(max_bytes + 1)
        response.close()
        # Decompress before truncating so we get valid content boundaries
        data = _decompress(data, content_encoding)
        if len(data) > max_bytes:
            data = data[:max_bytes]
        return content_type, data, charset

    raise urllib.error.URLError(f"Too many redirects (max {max_redirects})")


def _fetch_url_with_retry(
    url: str,
    timeout: int = WEB_FETCH_DEFAULT_TIMEOUT_SEC,
    max_bytes: int = WEB_FETCH_MAX_RESPONSE_BYTES,
    max_redirects: int = WEB_FETCH_MAX_REDIRECTS,
) -> tuple[str, bytes, str | None]:
    """Fetch URL with automatic retry on transient server errors (5xx, timeout)."""
    last_exc: Exception = RuntimeError("unreachable")
    for attempt in range(_MAX_FETCH_RETRIES + 1):
        try:
            return _fetch_url(url, timeout, max_bytes, max_redirects)
        except urllib.error.HTTPError as e:
            if e.code in _RETRY_HTTP_STATUS_CODES and attempt < _MAX_FETCH_RETRIES:
                last_exc = e
                time.sleep(2**attempt)
                continue
            raise
        except (TimeoutError, urllib.error.URLError) as e:
            # e is urllib.error.URLError here after the isinstance check fails
            is_timeout = True if isinstance(e, TimeoutError) else isinstance(e.reason, TimeoutError)
            if is_timeout and attempt < _MAX_FETCH_RETRIES:
                last_exc = e
                time.sleep(2**attempt)
                continue
            raise
    raise last_exc


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

        # Check cache
        cache_key = make_cache_key("fetch", url)
        cached = get_cached(cache_key)
        if cached is not None:
            return message.ToolResultMessage(status="success", output_text=cached)

        try:
            content_type, data, charset = await asyncio.to_thread(_fetch_url_with_retry, url)

            # Handle PDF files - must save binary content
            if content_type == "application/pdf" or _is_pdf_url(url):
                saved_path = _save_binary_content(url, data, ".pdf")
                if saved_path:
                    output = (
                        f"PDF file saved to: {saved_path}\n\n"
                        f"To read the PDF content, use the Read tool on this file path."
                    )
                    return message.ToolResultMessage(status="success", output_text=output)
                return message.ToolResultMessage(
                    status="error",
                    output_text=f"Failed to save PDF file (url={url})",
                )

            # Handle text content - save to file and return with path hint
            text = _decode_content(data, charset)
            processed = _process_content(content_type, text)
            wrapped = wrap_web_content(processed, source="Web Fetch", include_warning=True)
            saved_path = _save_text_content(url, processed)
            output = f"[Full content saved to {saved_path}]\n\n{wrapped}" if saved_path else wrapped

            set_cached(cache_key, output)
            return message.ToolResultMessage(status="success", output_text=output)

        except SSRFBlockedError as e:
            return message.ToolResultMessage(
                status="error",
                output_text=f"Blocked by security policy: {e} (url={url})",
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
