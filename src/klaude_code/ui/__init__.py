"""UI interfaces and lightweight displays.

This package intentionally contains only frontend-agnostic interfaces and
minimal display implementations.

Terminal (Rich/prompt-toolkit) UI lives in `klaude_code.tui`.
"""

# --- Abstract Interfaces ---
from .core.display import DisplayABC
from .core.input import InputProviderABC
from .debug_mode import DebugEventDisplay
from .exec_mode import ExecDisplay, StreamJsonDisplay


def create_exec_display(debug: bool = False, stream_json: bool = False) -> DisplayABC:
    """
    Create a display for exec (non-interactive) mode.

    Args:
        debug: If True, wrap the display with DebugEventDisplay to log all events.
        stream_json: If True, stream all events as JSON lines instead of normal output.

    Returns:
        A DisplayABC implementation that only outputs task results.
    """
    if stream_json:
        return StreamJsonDisplay()
    exec_display = ExecDisplay()
    if debug:
        return DebugEventDisplay(exec_display)
    return exec_display


__all__ = [
    "DebugEventDisplay",
    "DisplayABC",
    "ExecDisplay",
    "InputProviderABC",
    "StreamJsonDisplay",
    "create_exec_display",
]
