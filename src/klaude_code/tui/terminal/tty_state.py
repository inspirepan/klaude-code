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


# Depth of active flicker-safe write cycles (erase → body → redraw). Set by
# synchronized_in_terminal around the WHOLE cycle, unlike the app's
# _running_in_terminal flag which only covers the body.
_scrollback_cycle_depth = 0

# True while a prompt_toolkit renderer flush left a partially-written frame
# on fd 1 (tty stopped draining mid-write). The tail is drained by a loop
# writer callback; until then fd 1 may be mid-escape-sequence.
_renderer_tail_pending = False


def push_scrollback_cycle() -> None:
    global _scrollback_cycle_depth
    _scrollback_cycle_depth += 1


def pop_scrollback_cycle() -> None:
    global _scrollback_cycle_depth
    _scrollback_cycle_depth = max(0, _scrollback_cycle_depth - 1)


def set_renderer_tail_pending(pending: bool) -> None:
    global _renderer_tail_pending
    _renderer_tail_pending = pending


def renderer_tail_pending() -> bool:
    return _renderer_tail_pending


def scrollback_write_in_flight() -> bool:
    """Return True while fd 1 may be mid-escape-sequence.

    Covers two hazards: a flicker-safe scrollback write cycle in progress
    (payload drained in non-blocking chunks whose boundaries can fall
    mid-escape-sequence), and a renderer flush whose unfinished tail is
    still waiting for the tty to drain. A raw fd-1 write (title blink, OSC
    notification) landing in either gap corrupts terminal parsing, so
    direct writers must skip or reroute while this is set.
    """

    if _scrollback_cycle_depth > 0 or _renderer_tail_pending:
        return True
    try:
        from prompt_toolkit.application.current import get_app_or_none

        app = get_app_or_none()
    except Exception:
        return False
    return app is not None and bool(getattr(app, "_running_in_terminal", False))
