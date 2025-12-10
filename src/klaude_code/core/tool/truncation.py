import json
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from klaude_code import const
from klaude_code.protocol import model, tools


@dataclass
class TruncationResult:
    """Result of truncation operation."""

    output: str
    was_truncated: bool
    saved_file_path: str | None = None
    original_length: int = 0
    truncated_length: int = 0


FILE_SAVED_PATTERN = re.compile(r"<file_saved>([^<]+)</file_saved>")


def _extract_saved_file_path(output: str) -> str | None:
    """Extract file path from <file_saved> tag if present."""
    match = FILE_SAVED_PATTERN.search(output)
    return match.group(1) if match else None


def _extract_url_filename(url: str) -> str:
    """Extract a safe filename from a URL."""
    parsed = urlparse(url)
    # Combine host and path for a meaningful filename
    host = parsed.netloc.replace(".", "_").replace(":", "_")
    path = parsed.path.strip("/").replace("/", "_")
    name = f"{host}_{path}" if path else host
    # Sanitize: keep only alphanumeric, underscore, hyphen
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    # Limit length
    return name[:80] if len(name) > 80 else name


class TruncationStrategy(ABC):
    """Abstract base class for tool output truncation strategies."""

    @abstractmethod
    def truncate(self, output: str, tool_call: model.ToolCallItem | None = None) -> TruncationResult:
        """Truncate the output according to the strategy."""
        ...


class SimpleTruncationStrategy(TruncationStrategy):
    """Simple character-based truncation strategy."""

    def __init__(self, max_length: int = const.TOOL_OUTPUT_MAX_LENGTH):
        self.max_length = max_length

    def truncate(self, output: str, tool_call: model.ToolCallItem | None = None) -> TruncationResult:
        if len(output) > self.max_length:
            truncated_length = len(output) - self.max_length
            truncated_output = output[: self.max_length] + f"... (truncated {truncated_length} characters)"
            return TruncationResult(
                output=truncated_output,
                was_truncated=True,
                original_length=len(output),
                truncated_length=truncated_length,
            )
        return TruncationResult(output=output, was_truncated=False, original_length=len(output))


class SmartTruncationStrategy(TruncationStrategy):
    """Smart truncation strategy that saves full output to file and shows head/tail."""

    def __init__(
        self,
        max_length: int = const.TOOL_OUTPUT_MAX_LENGTH,
        head_chars: int = const.TOOL_OUTPUT_DISPLAY_HEAD,
        tail_chars: int = const.TOOL_OUTPUT_DISPLAY_TAIL,
        truncation_dir: str = const.TOOL_OUTPUT_TRUNCATION_DIR,
    ):
        self.max_length = max_length
        self.head_chars = head_chars
        self.tail_chars = tail_chars
        self.truncation_dir = Path(truncation_dir)

    def _get_file_identifier(self, tool_call: model.ToolCallItem | None) -> str:
        """Get a file identifier based on tool call. For WebFetch, use URL; otherwise use call_id."""
        if tool_call and tool_call.name == tools.WEB_FETCH:
            try:
                args = json.loads(tool_call.arguments)
                url = args.get("url", "")
                if url:
                    return _extract_url_filename(url)
            except (json.JSONDecodeError, TypeError):
                pass
        # Fallback to call_id
        if tool_call and tool_call.call_id:
            return tool_call.call_id.replace("/", "_")
        return "unknown"

    def _save_to_file(self, output: str, tool_call: model.ToolCallItem | None) -> str | None:
        """Save full output to file. Returns file path or None on failure."""
        try:
            self.truncation_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            tool_name = (tool_call.name if tool_call else "unknown").replace("/", "_")
            identifier = self._get_file_identifier(tool_call)
            filename = f"{tool_name}-{identifier}-{timestamp}.txt"
            file_path = self.truncation_dir / filename
            file_path.write_text(output, encoding="utf-8")
            return str(file_path)
        except OSError:
            return None

    def truncate(self, output: str, tool_call: model.ToolCallItem | None = None) -> TruncationResult:
        if tool_call and tool_call.name == tools.READ:
            # Do not truncate Read tool outputs
            return TruncationResult(output=output, was_truncated=False, original_length=len(output))

        original_length = len(output)

        if original_length <= self.max_length:
            return TruncationResult(output=output, was_truncated=False, original_length=original_length)

        # Check if file was already saved (e.g., by WebFetch)
        existing_file_path = _extract_saved_file_path(output)
        saved_file_path = existing_file_path or self._save_to_file(output, tool_call)

        # Strip existing <file_saved> tag to avoid duplication in head/tail
        content_to_truncate = FILE_SAVED_PATTERN.sub("", output).lstrip("\n") if existing_file_path else output
        content_length = len(content_to_truncate)

        truncated_length = content_length - self.head_chars - self.tail_chars
        head_content = content_to_truncate[: self.head_chars]
        tail_content = content_to_truncate[-self.tail_chars :]

        # Build truncated output with file info
        if saved_file_path:
            header = (
                f"<system-reminder>Output truncated ({truncated_length} chars hidden) to reduce context usage. "
                f"Full content saved to <file_saved>{saved_file_path}</file_saved>. "
                f"Use Read(offset, limit) or rg to inspect if needed. "
                f"Showing first {self.head_chars} and last {self.tail_chars} chars:</system-reminder>\n\n"
            )
        else:
            header = (
                f"<system-reminder>Output truncated ({truncated_length} chars hidden) to reduce context usage. "
                f"Showing first {self.head_chars} and last {self.tail_chars} chars:</system-reminder>\n\n"
            )

        truncated_output = (
            f"{header}{head_content}\n\n"
            f"<system-reminder>... {truncated_length} characters omitted ...</system-reminder>\n\n"
            f"{tail_content}"
        )

        return TruncationResult(
            output=truncated_output,
            was_truncated=True,
            saved_file_path=saved_file_path,
            original_length=original_length,
            truncated_length=truncated_length,
        )


_default_strategy: TruncationStrategy = SmartTruncationStrategy()


def get_truncation_strategy() -> TruncationStrategy:
    """Get the current truncation strategy."""
    return _default_strategy


def set_truncation_strategy(strategy: TruncationStrategy) -> None:
    """Set the truncation strategy to use."""
    global _default_strategy
    _default_strategy = strategy


def truncate_tool_output(output: str, tool_call: model.ToolCallItem | None = None) -> TruncationResult:
    """Truncate tool output using the current strategy."""
    return get_truncation_strategy().truncate(output, tool_call)
