import contextlib
import os
import sys

from klaude_code.log import DebugType, log_debug


def _format_session_title(session_title: str | None) -> str | None:
    if not session_title:
        return None
    single_line = " ".join(session_title.split())
    if not single_line:
        return None
    return single_line[:80]


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
    """Update terminal title with folder name, optional model name, and session title."""
    formatted_session_title = _format_session_title(session_title)
    if formatted_session_title:
        title = formatted_session_title
        if prefix:
            title = f"{prefix} {title}"
        set_terminal_title(title)
        return

    folder_name = os.path.basename(work_dir or os.getcwd())
    if model_name:
        model_alias = model_name.split("@")[0]
        title = f"klaude [{model_alias}] · {folder_name}"
    else:
        title = f"klaude · {folder_name}"

    if prefix:
        title = f"{prefix} {title}"

    set_terminal_title(title)
