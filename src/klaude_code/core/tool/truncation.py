import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from klaude_code.config.constants import (
    TOOL_OUTPUT_DISPLAY_HEAD,
    TOOL_OUTPUT_DISPLAY_TAIL,
    TOOL_OUTPUT_MAX_LENGTH,
    TOOL_OUTPUT_TRUNCATION_DIR,
)


@dataclass
class TruncationResult:
    """Result of truncation operation."""

    output: str
    was_truncated: bool
    saved_file_path: str | None = None
    original_length: int = 0
    truncated_length: int = 0


class TruncationStrategy(ABC):
    """Abstract base class for tool output truncation strategies."""

    @abstractmethod
    def truncate(self, output: str, tool_name: str | None = None, call_id: str | None = None) -> TruncationResult:
        """Truncate the output according to the strategy."""
        ...


class SimpleTruncationStrategy(TruncationStrategy):
    """Simple character-based truncation strategy."""

    def __init__(self, max_length: int = TOOL_OUTPUT_MAX_LENGTH):
        self.max_length = max_length

    def truncate(self, output: str, tool_name: str | None = None, call_id: str | None = None) -> TruncationResult:
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
        max_length: int = TOOL_OUTPUT_MAX_LENGTH,
        head_chars: int = TOOL_OUTPUT_DISPLAY_HEAD,
        tail_chars: int = TOOL_OUTPUT_DISPLAY_TAIL,
        truncation_dir: str = TOOL_OUTPUT_TRUNCATION_DIR,
    ):
        self.max_length = max_length
        self.head_chars = head_chars
        self.tail_chars = tail_chars
        self.truncation_dir = Path(truncation_dir)

    def _save_to_file(self, output: str, tool_name: str | None, call_id: str | None) -> str | None:
        """Save full output to file. Returns file path or None on failure."""
        try:
            self.truncation_dir.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time())
            safe_tool_name = (tool_name or "unknown").replace("/", "_")
            safe_call_id = (call_id or "unknown").replace("/", "_")
            filename = f"{safe_tool_name}-{safe_call_id}-{timestamp}.txt"
            file_path = self.truncation_dir / filename
            file_path.write_text(output, encoding="utf-8")
            return str(file_path)
        except (OSError, IOError):
            return None

    def truncate(self, output: str, tool_name: str | None = None, call_id: str | None = None) -> TruncationResult:
        original_length = len(output)

        if original_length <= self.max_length:
            return TruncationResult(output=output, was_truncated=False, original_length=original_length)

        # Save full output to file
        saved_file_path = self._save_to_file(output, tool_name, call_id)

        truncated_length = original_length - self.head_chars - self.tail_chars
        head_content = output[: self.head_chars]
        tail_content = output[-self.tail_chars :]

        # Build truncated output with file info
        if saved_file_path:
            header = (
            f"<system-reminder>Output truncated: {truncated_length} chars hidden. "
            f"Full output saved to {saved_file_path}. "
            f"Use Read with limit+offset or rg/grep to inspect.\n"
            f"Showing first {self.head_chars} and last {self.tail_chars} chars:</system-reminder>\n\n"
            )
        else:
            header = (
            f"<system-reminder>Output truncated: {truncated_length} chars hidden. "
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


def truncate_tool_output(output: str, tool_name: str | None = None, call_id: str | None = None) -> TruncationResult:
    """Truncate tool output using the current strategy."""
    return get_truncation_strategy().truncate(output, tool_name, call_id)
