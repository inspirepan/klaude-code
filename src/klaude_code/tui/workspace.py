"""Client-side active workspace directory.

The TUI process serves exactly one session at a time; that session's
work_dir is the base for @ completion, drag-drop path conversion, path
shortening, and header info. It usually equals the process CWD, but
diverges when attaching to a session rooted in another directory
(``klaude attach <id>``), so TUI code must read it from here instead of
``Path.cwd()``.
"""

from __future__ import annotations

from pathlib import Path

_active_work_dir: Path | None = None


def set_active_work_dir(work_dir: Path) -> None:
    """Record the attached session's work_dir (called on session-info updates)."""
    global _active_work_dir
    _active_work_dir = work_dir


def active_work_dir() -> Path:
    """The attached session's work_dir, falling back to the process CWD before attach."""
    return _active_work_dir if _active_work_dir is not None else Path.cwd()
