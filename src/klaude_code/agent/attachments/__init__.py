"""Agent attachment package.

Shared helpers for <system-reminder> content produced by attachments live here.
Each concrete attachment (files, memory, skills, …) is responsible for
truncating its own output; these helpers provide a consistent Read-tool-style
notice so the agent always knows how to fetch the full content.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LineTruncationResult:
    """Outcome of :func:`truncate_text_by_lines`."""

    text: str
    total_lines: int
    kept_lines: int
    truncated: bool

    @property
    def hidden_lines(self) -> int:
        return max(0, self.total_lines - self.kept_lines)


def truncate_text_by_lines(text: str, *, max_lines: int) -> LineTruncationResult:
    """Keep the first ``max_lines`` lines; report total/hidden line counts.

    The trailing newline (if any) is preserved only when the text was not
    truncated, matching Read tool behaviour where a truncated view never
    ends with a bare newline before the notice.
    """
    if max_lines <= 0:
        return LineTruncationResult(
            text="", total_lines=text.count("\n") + (1 if text else 0), kept_lines=0, truncated=bool(text)
        )

    lines = text.splitlines()
    total = len(lines)
    if total <= max_lines:
        return LineTruncationResult(text=text, total_lines=total, kept_lines=total, truncated=False)

    kept = "\n".join(lines[:max_lines])
    return LineTruncationResult(text=kept, total_lines=total, kept_lines=max_lines, truncated=True)
