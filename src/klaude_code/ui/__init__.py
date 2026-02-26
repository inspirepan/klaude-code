"""UI interfaces and lightweight displays.

This package intentionally contains only frontend-agnostic interfaces and
minimal display implementations.

Terminal (Rich/prompt-toolkit) UI lives in `klaude_code.tui`.
"""

# --- Abstract Interfaces ---
from .core.display import DisplayABC
from .core.input import InputProviderABC

__all__ = [
    "DisplayABC",
    "InputProviderABC",
]
