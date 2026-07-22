from __future__ import annotations

import asyncio
import contextlib
import os
import sys

from klaude_code.log import DebugType, log_debug
from klaude_code.tui.terminal.tty_state import scrollback_write_in_flight, stdout_writable

# Blink state: cycles a single-glyph Braille spinner to keep title width stable.
_BLINK_PREFIXES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
_BLINK_INTERVAL = 0.08  # seconds
_OVERRIDE_BLINK_TICKS = 6
_OVERRIDE_DIM_PREFIX = "❔"

_blink_task: asyncio.Task[None] | None = None
_blink_model_name: str | None = None
_blink_session_title: str | None = None
_title_override_prefix: str | None = None

# Retry state: a title write dropped on a busy tty is re-attempted until it
# lands, so one-shot updates (the final ✅/❌ after a task) aren't lost.
_RETRY_INTERVAL = 0.08  # seconds
_RETRY_MAX_ATTEMPTS = 62  # ~5s before giving up

_pending_title: str | None = None
_retry_task: asyncio.Task[None] | None = None


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


def _try_write_title(title: str) -> bool:
    """Write the OSC title sequence; True when done (or permanently skipped)."""
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            log_debug("Terminal title skipped: stdout is not a TTY", debug_type=DebugType.TERMINAL)
            return True
    except Exception:
        log_debug("Terminal title skipped: failed to probe TTY state", debug_type=DebugType.TERMINAL)
        return True

    # A stalled terminal (not draining the pty) would turn this write into an
    # event-loop-blocking call; drop the frame instead.
    if not stdout_writable():
        log_debug("Terminal title skipped: stdout not writable (tty backpressure)", debug_type=DebugType.TERMINAL)
        return False

    # A scrollback drain may be mid-frame with its payload split at an
    # arbitrary byte; injecting this OSC there would corrupt terminal
    # parsing. Drop the frame.
    if scrollback_write_in_flight():
        log_debug("Terminal title skipped: scrollback write in flight", debug_type=DebugType.TERMINAL)
        return False

    log_debug(f"Terminal title set: {title}", debug_type=DebugType.TERMINAL)
    stream.write(f"\033]0;{title}\007")
    with contextlib.suppress(Exception):
        stream.flush()
    return True


def set_terminal_title(title: str) -> None:
    """Set terminal window title using an ANSI escape sequence."""
    global _pending_title
    if _try_write_title(title):
        _pending_title = None
        _cancel_title_retry()
        return

    # The tty is busy. While the blink loop runs, the next 80ms tick rewrites
    # the title anyway — but the final title of a task (✅/❌) is a one-shot
    # write issued right when the last message is draining to scrollback, so
    # it must be retried or it's lost and the stale spinner glyph sticks.
    _pending_title = title
    _ensure_title_retry()


def _ensure_title_retry() -> None:
    global _retry_task
    if _retry_task is not None and not _retry_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        _retry_task = None
        return
    _retry_task = loop.create_task(_retry_loop())


def _cancel_title_retry() -> None:
    global _retry_task
    if _retry_task is not None:
        _retry_task.cancel()
        _retry_task = None


async def _retry_loop() -> None:
    global _pending_title
    for _ in range(_RETRY_MAX_ATTEMPTS):
        await asyncio.sleep(_RETRY_INTERVAL)
        title = _pending_title
        if title is None:
            return
        if _try_write_title(title):
            _pending_title = None
            return


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
        if _title_override_prefix is None:
            prefix = _BLINK_PREFIXES[idx % len(_BLINK_PREFIXES)]
        else:
            prefix = _title_override_prefix if (idx // _OVERRIDE_BLINK_TICKS) % 2 == 0 else _OVERRIDE_DIM_PREFIX
        update_terminal_title(
            _blink_model_name,
            prefix=prefix,
            session_title=_blink_session_title,
        )
        idx += 1
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


def set_terminal_title_override(prefix: str) -> None:
    """Temporarily replace the active-task spinner with a status prefix."""
    global _title_override_prefix
    _title_override_prefix = prefix
    update_terminal_title(_blink_model_name, prefix=prefix, session_title=_blink_session_title)


def clear_terminal_title_override() -> None:
    """Clear a temporary status prefix and restore the active-task title."""
    global _title_override_prefix
    _title_override_prefix = None
    prefix = _BLINK_PREFIXES[0] if is_title_blinking() else None
    update_terminal_title(_blink_model_name, prefix=prefix, session_title=_blink_session_title)


def stop_terminal_title_blink() -> None:
    """Cancel the blink loop if running."""
    global _blink_task, _title_override_prefix, _pending_title
    if _blink_task is not None:
        _blink_task.cancel()
        _blink_task = None
    _title_override_prefix = None
    # Drop any retry carrying a stale blink frame; the caller's follow-up
    # title update re-arms the retry if the tty is still busy.
    _pending_title = None
    _cancel_title_retry()
