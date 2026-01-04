"""Application-layer runtime helpers.

This package coordinates core execution (Executor) with frontend displays.
Terminal-specific rendering and input handling live in `klaude_code.tui`.
"""

from .runtime import AppInitConfig

__all__ = [
    "AppInitConfig",
]
