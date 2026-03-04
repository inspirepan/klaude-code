import contextlib
import os
import sys


def set_terminal_title(title: str) -> None:
    """Set terminal window title using an ANSI escape sequence."""
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            return
    except Exception:
        return

    stream.write(f"\033]0;{title}\007")
    with contextlib.suppress(Exception):
        stream.flush()


def update_terminal_title(model_name: str | None = None, *, prefix: str | None = None, work_dir: str | None = None) -> None:
    """Update terminal title with folder name and optional model name."""
    folder_name = os.path.basename(work_dir or os.getcwd())
    if model_name:
        model_alias = model_name.split("@")[0]
        title = f"klaude [{model_alias}] · {folder_name}"
    else:
        title = f"klaude · {folder_name}"

    if prefix:
        title = f"{prefix} {title}"

    set_terminal_title(title)
