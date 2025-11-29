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

from .base.debug_event_display import DebugEventDisplay

# --- Abstract Interfaces ---
from .base.display_abc import DisplayABC
from .base.exec_display import ExecDisplay
from .base.input_abc import InputProviderABC
from .base.terminal_notifier import TerminalNotifier

# --- Display Mode Implementations ---
from .repl.display import REPLDisplay

# --- Input Implementations ---
from .repl.input import PromptToolkitInput


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


def create_exec_display(debug: bool = False) -> DisplayABC:
    """
    Create a display for exec (non-interactive) mode.

    Args:
        debug: If True, wrap the display with DebugEventDisplay to log all events.

    Returns:
        A DisplayABC implementation that only outputs task results.
    """
    exec_display = ExecDisplay()
    if debug:
        return DebugEventDisplay(exec_display)
    return exec_display


__all__ = [
    # Abstract interfaces
    "DisplayABC",
    "InputProviderABC",
    # Display mode implementations
    "REPLDisplay",
    "ExecDisplay",
    "DebugEventDisplay",
    # Input implementations
    "PromptToolkitInput",
    # Factory functions
    "create_default_display",
    "create_exec_display",
    # Supporting types
    "TerminalNotifier",
]
