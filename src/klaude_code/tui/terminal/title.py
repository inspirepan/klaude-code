from __future__ import annotations

import asyncio
import contextlib
import os
import sys

from klaude_code.log import DebugType, log_debug

# Blink state: cycles a single-glyph Braille spinner to keep title width stable.
_BLINK_PREFIXES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_BLINK_INTERVAL = 0.08  # seconds

_blink_task: asyncio.Task[None] | None = None
_blink_model_name: str | None = None
_blink_session_title: str | None = None


def _format_session_title(session_title: str | None) -> str | None:
    if not session_title:
        return None
    single_line = " ".join(session_title.split())
    if not single_line:
        return None
    return single_line[:80]


def _project_name(work_dir: str | None) -> str:
    folder_name = os.path.basename(work_dir or os.getcwd())
    return folder_name or "klaude"


def _build_terminal_title(work_dir: str | None, session_title: str | None) -> str:
    project_name = _project_name(work_dir)
    formatted_session_title = _format_session_title(session_title)
    if formatted_session_title:
        return f"{formatted_session_title} · {project_name}"
    return f"klaude · {project_name}"


def set_terminal_title(title: str) -> None:
    """Set terminal window title using an ANSI escape sequence."""
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            log_debug("Terminal title skipped: stdout is not a TTY", debug_type=DebugType.TERMINAL)
            return
    except Exception:
        log_debug("Terminal title skipped: failed to probe TTY state", debug_type=DebugType.TERMINAL)
        return

    log_debug(f"Terminal title set: {title}", debug_type=DebugType.TERMINAL)
    stream.write(f"\033]0;{title}\007")
    with contextlib.suppress(Exception):
        stream.flush()


def update_terminal_title(
    model_name: str | None = None,
    *,
    prefix: str | None = None,
    work_dir: str | None = None,
    session_title: str | None = None,
) -> None:
    """Update terminal title with an optional status prefix and session title."""
    title = _build_terminal_title(work_dir, session_title)

    if prefix:
        title = f"{prefix} {title}"

    set_terminal_title(title)


# ---------------------------------------------------------------------------
# Terminal title blink (single-glyph spinner while task is active)
# ---------------------------------------------------------------------------


async def _blink_loop() -> None:
    idx = 0
    while True:
        update_terminal_title(
            _blink_model_name,
            prefix=_BLINK_PREFIXES[idx],
            session_title=_blink_session_title,
        )
        idx = (idx + 1) % len(_BLINK_PREFIXES)
        await asyncio.sleep(_BLINK_INTERVAL)


def start_terminal_title_blink(model_name: str | None, session_title: str | None) -> None:
    """Start cycling the terminal title prefix through the active-task spinner."""
    global _blink_task, _blink_model_name, _blink_session_title
    stop_terminal_title_blink()
    _blink_model_name = model_name
    _blink_session_title = session_title
    _blink_task = asyncio.create_task(_blink_loop())


def update_blink_params(model_name: str | None = None, session_title: str | None = None) -> None:
    """Update parameters for a running blink loop (picked up on next tick)."""
    global _blink_model_name, _blink_session_title
    if model_name is not None:
        _blink_model_name = model_name
    if session_title is not None:
        _blink_session_title = session_title


def is_title_blinking() -> bool:
    return _blink_task is not None and not _blink_task.done()


def stop_terminal_title_blink() -> None:
    """Cancel the blink loop if running."""
    global _blink_task
    if _blink_task is not None:
        _blink_task.cancel()
        _blink_task = None
