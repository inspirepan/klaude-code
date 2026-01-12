import contextlib
import os
import sys


def set_terminal_title(title: str) -> None:
    """Set terminal window title using an ANSI escape sequence."""
    # Never write terminal control sequences when stdout is not a TTY (pipes/CI/redirects).
    # This avoids corrupting machine-readable output (e.g., JSON streaming) and log captures.
    #
    # Use the original stdout to bypass prompt_toolkit's `patch_stdout()`. Writing OSC
    # sequences to the patched stdout can cause them to appear as visible text.
    stream = getattr(sys, "__stdout__", None) or sys.stdout
    try:
        if not stream.isatty():
            return
    except Exception:
        return

    stream.write(f"\033]0;{title}\007")
    with contextlib.suppress(Exception):
        stream.flush()


def update_terminal_title(model_name: str | None = None) -> None:
    """Update terminal title with folder name and optional model name."""
    folder_name = os.path.basename(os.getcwd())
    if model_name:
        # Strip provider suffix (e.g., opus@openrouter -> opus)
        model_alias = model_name.split("@")[0]
        set_terminal_title(f"klaude [{model_alias}] · {folder_name}")
    else:
        set_terminal_title(f"klaude · {folder_name}")
