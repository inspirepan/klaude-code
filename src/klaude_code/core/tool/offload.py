"""Tool Output Offload & Truncation Strategies
==============================================

This module manages how tool outputs are truncated and offloaded to files
to reduce LLM context usage while preserving access to full content.

Design Principles
-----------------
Different tools have different output characteristics, so we apply
tool-specific strategies:

┌─────────────┬─────────────────────────┬─────────────────┬────────────────────────────┐
│ Tool        │ Truncation Style        │ Offload Policy  │ Rationale                  │
├─────────────┼─────────────────────────┼─────────────────┼────────────────────────────┤
│ Read        │ Head-focused            │ Never           │ Source file already exists │
│             │ (line/char limits)      │                 │ on filesystem; use offset/ │
│             │                         │                 │ limit to paginate          │
├─────────────┼─────────────────────────┼─────────────────┼────────────────────────────┤
│ Others      │ Head + Tail             │ On threshold    │ Generic fallback strategy  │
│             │ (lines first, then      │                 │ (2000 lines or 40k chars)  │
│             │ chars as fallback)      │                 │                            │
└─────────────┴─────────────────────────┴─────────────────┴────────────────────────────┘

Implementation Notes
--------------------
- Read tool handles its own truncation internally (see read_tool.py)
- WebFetch handles its own file saving internally (see web_fetch_tool.py)
- All offload decisions are centralized in this module
"""

from __future__ import annotations

import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Protocol

from klaude_code.const import (
    TOOL_OUTPUT_DISPLAY_HEAD,
    TOOL_OUTPUT_DISPLAY_HEAD_LINES,
    TOOL_OUTPUT_DISPLAY_TAIL,
    TOOL_OUTPUT_DISPLAY_TAIL_LINES,
    TOOL_OUTPUT_MAX_LENGTH,
    TOOL_OUTPUT_MAX_LINES,
    TOOL_OUTPUT_TRUNCATION_DIR,
)
from klaude_code.protocol import tools


class ToolCallLike(Protocol):
    """Protocol for tool call objects."""

    @property
    def tool_name(self) -> str: ...


# =============================================================================
# Data Structures
# =============================================================================


class OffloadPolicy(Enum):
    """When to offload full output to filesystem."""

    NEVER = auto()  # Never offload (e.g., Read - source file exists)
    ON_THRESHOLD = auto()  # Offload only when exceeding size threshold


@dataclass
class OffloadResult:
    """Result of offload/truncation operation."""

    output: str
    was_truncated: bool
    offloaded_path: str | None = None
    original_length: int = 0
    truncated_chars: int = 0


# =============================================================================
# Strategy Interface
# =============================================================================


class OffloadStrategy(ABC):
    """Base class for tool-specific offload strategies."""

    @abstractmethod
    def process(self, output: str, tool_call: ToolCallLike | None = None) -> OffloadResult:
        """Process tool output: truncate and optionally offload."""
        ...


# =============================================================================
# Strategy Implementations
# =============================================================================


class ReadToolStrategy(OffloadStrategy):
    """Strategy for Read tool output.

    - Truncation: Head-focused (handled internally by read_tool.py)
    - Offload: Never (source file already on filesystem)

    This strategy is a pass-through since Read tool handles its own truncation.
    """

    def process(self, output: str, tool_call: ToolCallLike | None = None) -> OffloadResult:
        return OffloadResult(output=output, was_truncated=False, original_length=len(output))


class HeadTailOffloadStrategy(OffloadStrategy):
    """Strategy for Bash and generic tools.

    - Truncation: Head + Tail (preserve both ends, errors often at end)
    - Offload: Configurable (default: on threshold)
    """

    def __init__(
        self,
        max_length: int = TOOL_OUTPUT_MAX_LENGTH,
        head_chars: int = TOOL_OUTPUT_DISPLAY_HEAD,
        tail_chars: int = TOOL_OUTPUT_DISPLAY_TAIL,
        max_lines: int = TOOL_OUTPUT_MAX_LINES,
        head_lines: int = TOOL_OUTPUT_DISPLAY_HEAD_LINES,
        tail_lines: int = TOOL_OUTPUT_DISPLAY_TAIL_LINES,
        offload_dir: str | None = None,
        policy: OffloadPolicy = OffloadPolicy.ON_THRESHOLD,
    ):
        self.max_length = max_length
        self.head_chars = head_chars
        self.tail_chars = tail_chars
        self.max_lines = max_lines
        self.head_lines = head_lines
        self.tail_lines = tail_lines
        self.offload_dir = Path(offload_dir or TOOL_OUTPUT_TRUNCATION_DIR)
        self._policy = policy

    def _save_to_file(self, output: str, tool_call: ToolCallLike | None) -> str | None:
        """Save full output to file. Returns path or None on failure."""
        try:
            self.offload_dir.mkdir(parents=True, exist_ok=True)
            tool_name = (tool_call.tool_name if tool_call else "unknown").replace("/", "_").lower()
            random_hex = secrets.token_hex(8)
            filename = f"klaude-{tool_name}-{random_hex}.log"
            file_path = self.offload_dir / filename
            file_path.write_text(output, encoding="utf-8")
            return str(file_path)
        except OSError:
            return None

    def _should_offload(self, needs_truncation: bool) -> bool:
        """Determine if content should be offloaded based on policy."""
        if self._policy == OffloadPolicy.NEVER:
            return False
        # ON_THRESHOLD: offload only when truncating
        return needs_truncation

    def _truncate_by_lines(self, output: str, lines: list[str], offloaded_path: str | None) -> tuple[str, int]:
        """Truncate by lines. Returns (truncated_output, hidden_lines)."""
        total_lines = len(lines)
        hidden_lines = total_lines - self.head_lines - self.tail_lines
        head = "\n".join(lines[: self.head_lines])
        tail = "\n".join(lines[-self.tail_lines :])

        if offloaded_path:
            header = (
                f"<system-reminder>Output truncated due to length. "
                f"Showing first {self.head_lines} and last {self.tail_lines} lines of {total_lines} lines. "
                f"Full output saved to: {offloaded_path} </system-reminder>\n\n"
            )
        else:
            header = (
                f"<system-reminder>Output truncated due to length. "
                f"Showing first {self.head_lines} and last {self.tail_lines} lines of {total_lines} lines."
                f"</system-reminder>\n\n"
            )

        truncated_output = f"{header}{head}\n\n<...{hidden_lines} lines omitted...>\n\n{tail}"
        return truncated_output, hidden_lines

    def _truncate_by_chars(self, output: str, offloaded_path: str | None) -> tuple[str, int]:
        """Truncate by characters. Returns (truncated_output, hidden_chars)."""
        original_length = len(output)
        hidden_chars = original_length - self.head_chars - self.tail_chars
        head = output[: self.head_chars]
        tail = output[-self.tail_chars :]

        if offloaded_path:
            header = (
                f"<system-reminder>Output truncated due to length. "
                f"Showing first {self.head_chars} and last {self.tail_chars} chars of {original_length} chars. "
                f"Full output saved to: {offloaded_path} </system-reminder>\n\n"
            )
        else:
            header = (
                f"<system-reminder>Output truncated due to length. "
                f"Showing first {self.head_chars} and last {self.tail_chars} chars of {original_length} chars."
                f"</system-reminder>\n\n"
            )

        truncated_output = f"{header}{head}\n\n<...{hidden_chars} chars omitted...>\n\n{tail}"
        return truncated_output, hidden_chars

    def process(self, output: str, tool_call: ToolCallLike | None = None) -> OffloadResult:
        original_length = len(output)
        lines = output.splitlines()
        total_lines = len(lines)

        # Check if truncation is needed (by lines or by chars)
        needs_line_truncation = total_lines > self.max_lines
        needs_char_truncation = original_length > self.max_length
        needs_truncation = needs_line_truncation or needs_char_truncation

        # No truncation needed
        if not needs_truncation:
            return OffloadResult(
                output=output,
                was_truncated=False,
                original_length=original_length,
            )

        # Truncation needed - offload if policy allows
        offloaded_path = None
        if self._should_offload(needs_truncation):
            offloaded_path = self._save_to_file(output, tool_call)

        # Prefer line-based truncation if line limit exceeded
        if needs_line_truncation:
            truncated_output, hidden = self._truncate_by_lines(output, lines, offloaded_path)
        else:
            truncated_output, hidden = self._truncate_by_chars(output, offloaded_path)

        return OffloadResult(
            output=truncated_output,
            was_truncated=True,
            offloaded_path=offloaded_path,
            original_length=original_length,
            truncated_chars=hidden,
        )


# =============================================================================
# Strategy Registry
# =============================================================================

_STRATEGY_REGISTRY: dict[str, OffloadStrategy] = {
    tools.READ: ReadToolStrategy(),
}

_DEFAULT_STRATEGY = HeadTailOffloadStrategy()


def get_strategy(tool_name: str | None) -> OffloadStrategy:
    """Get the appropriate strategy for a tool."""
    if tool_name and tool_name in _STRATEGY_REGISTRY:
        return _STRATEGY_REGISTRY[tool_name]
    return _DEFAULT_STRATEGY


# =============================================================================
# Public API
# =============================================================================


def offload_tool_output(output: str, tool_call: ToolCallLike | None = None) -> OffloadResult:
    """Process tool output with appropriate offload/truncation strategy.

    This is the main entry point. It selects the right strategy based on
    the tool type and applies truncation/offload as needed.
    """
    tool_name = tool_call.tool_name if tool_call else None
    strategy = get_strategy(tool_name)
    return strategy.process(output, tool_call)
