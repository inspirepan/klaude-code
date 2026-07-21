"""Probe whether the real stdout tty can accept writes without blocking.

The TUI event loop must never issue a write that can block: when the
terminal emulator stops draining the pty (window occluded, compositor
stall, slow renderer), a single blocking ``write``/``flush`` on fd 1
freezes the whole loop — spinner, display consumer, and the in-flight
LLM stream alike. Timer-driven writers (title blink, spinner repaints)
should consult :func:`stdout_writable` and skip the frame instead.
"""

from __future__ import annotations

import select
import sys


def stdout_writable() -> bool:
    """Return True when fd 1 has buffer space for a small write.

    Defaults to True on any probe failure so callers degrade to the old
    (blocking) behavior rather than suppressing output forever.
    """

    stream = getattr(sys, "__stdout__", None)
    if stream is None:
        return True
    try:
        fd = stream.fileno()
    except Exception:
        return True
    try:
        _, writable, _ = select.select([], [fd], [], 0)
    except Exception:
        return True
    return bool(writable)
