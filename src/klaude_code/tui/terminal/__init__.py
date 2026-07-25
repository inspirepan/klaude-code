# Terminal utilities
import os
from functools import lru_cache


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
