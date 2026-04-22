# Terminal utilities
import os
from functools import lru_cache


@lru_cache(maxsize=1)
def supports_osc8_hyperlinks() -> bool:
    """Check if the current terminal supports OSC 8 hyperlinks.

    Based on known terminal support. Returns False for unknown terminals.
    """
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()

    # Known terminals that do NOT support OSC 8
    unsupported = ("warp", "apple_terminal")
    if any(t in term_program for t in unsupported):
        return False

    # Known terminals that support OSC 8
    supported = (
        "iterm.app",
        "ghostty",
        "wezterm",
        "kitty",
        "alacritty",
        "hyper",
        "contour",
        "vscode",
    )
    if any(t in term_program for t in supported):
        return True

    # Kitty sets TERM to xterm-kitty
    if "kitty" in term:
        return True

    # Ghostty sets TERM to xterm-ghostty
    if "ghostty" in term:
        return True

    # Windows Terminal
    if os.environ.get("WT_SESSION"):
        return True

    # VTE-based terminals (GNOME Terminal, etc.) version 0.50+
    vte_version = os.environ.get("VTE_VERSION", "")
    if vte_version:
        try:
            if int(vte_version) >= 5000:
                return True
        except ValueError:
            pass

    # Default to False for unknown terminals
    return False


@lru_cache(maxsize=1)
def supports_kitty_graphics() -> bool:
    """Check if the current terminal supports the Kitty graphics protocol."""
    term_program = os.environ.get("TERM_PROGRAM", "").lower()
    term = os.environ.get("TERM", "").lower()

    # Kitty
    if "kitty" in term_program or "kitty" in term:
        return True

    # Ghostty supports Kitty graphics protocol
    if "ghostty" in term_program or "ghostty" in term:
        return True

    # WezTerm supports Kitty graphics protocol
    if "wezterm" in term_program:
        return True

    # Warp supports Kitty graphics protocol since v0.2025.03.26
    if "warp" in term_program:
        return True

    # Konsole (KDE) supports Kitty graphics protocol
    return bool(os.environ.get("KONSOLE_VERSION"))
