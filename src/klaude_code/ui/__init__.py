"""
UI Module - Display and Input Abstractions for klaude-code

This module provides the UI layer for klaude-code, including display modes
and input providers. The UI is designed around three main concepts:

Display Modes:
- REPLDisplay: Interactive terminal mode with Rich rendering, spinners, and live updates
- ExecDisplay: Non-interactive exec mode that only outputs task results
- DebugEventDisplay: Decorator that logs all events for debugging purposes

Input Providers:
- PromptToolkitInput: Interactive input with prompt-toolkit (completions, keybindings)

Factory Functions:
- create_default_display(): Creates the appropriate display for interactive mode
- create_exec_display(): Creates the appropriate display for exec mode
"""

# --- Abstract Interfaces ---
from .core.display import DisplayABC
from .core.input import InputProviderABC
from .modes.debug.display import DebugEventDisplay
from .modes.exec.display import ExecDisplay, StreamJsonDisplay

# --- Display Mode Implementations ---
from .modes.repl.display import REPLDisplay

# --- Input Implementations ---
from .modes.repl.input_prompt_toolkit import PromptToolkitInput
from .terminal.notifier import TerminalNotifier


def create_default_display(
    debug: bool = False,
    theme: str | None = None,
    notifier: TerminalNotifier | None = None,
) -> DisplayABC:
    """
    Create the default display for interactive REPL mode.

    Args:
        debug: If True, wrap the display with DebugEventDisplay to log all events.
        theme: Optional theme name ("light" or "dark") for syntax highlighting.
        notifier: Optional terminal notifier for desktop notifications.

    Returns:
        A DisplayABC implementation suitable for interactive use.
    """
    repl_display = REPLDisplay(theme=theme, notifier=notifier)
    if debug:
        return DebugEventDisplay(repl_display)
    return repl_display


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
    "PromptToolkitInput",
    "REPLDisplay",
    "StreamJsonDisplay",
    "TerminalNotifier",
    "create_default_display",
    "create_exec_display",
]
