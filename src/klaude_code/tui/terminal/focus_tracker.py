"""Terminal focus tracker.

Tracks terminal window focus state via DECSET 1004 (`\\x1b[?1004h`), which
asks the terminal to send `\\x1b[I` (FocusIn) / `\\x1b[O` (FocusOut) on
window focus change. State is populated from two sources depending on
whether prompt_toolkit currently owns stdin:

- Prompt phase: prompt_toolkit's Vt100Parser converts the sequences into
  `Keys.FocusIn` / `Keys.FocusOut` which a key binding forwards here.
- LLM-running phase: the esc_interrupt_monitor reads stdin raw and
  recognizes the sequences, forwarding them here as well.

Both call sites may run on a non-loop thread, so `set_state()` is
thread-safe and dispatches subscriber callbacks on the asyncio loop.

Default state is UNKNOWN — terminals that do not support DECSET 1004
simply never transition, and downstream consumers should treat UNKNOWN
as "feature disabled".
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from enum import Enum
from threading import Lock


class FocusState(str, Enum):
    UNKNOWN = "unknown"
    FOCUSED = "focused"
    BLURRED = "blurred"


Subscriber = Callable[[FocusState], None]


class FocusTracker:
    def __init__(self) -> None:
        self._state: FocusState = FocusState.UNKNOWN
        self._subscribers: list[Subscriber] = []
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Associate the tracker with an event loop so callbacks from
        background threads are dispatched via ``call_soon_threadsafe``.
        Call once at TUI startup.
        """
        self._loop = loop

    def get_state(self) -> FocusState:
        return self._state

    def set_state(self, state: FocusState) -> None:
        """Update focus state and fire subscribers. Safe to call from any thread."""
        with self._lock:
            if state == self._state:
                return
            self._state = state
            subscribers = list(self._subscribers)

        loop = self._loop
        for cb in subscribers:
            if loop is not None and loop.is_running():
                with contextlib.suppress(RuntimeError):
                    loop.call_soon_threadsafe(cb, state)
            else:
                # No loop bound yet; best-effort direct call.
                with contextlib.suppress(Exception):
                    cb(state)

    def subscribe(self, cb: Subscriber) -> Callable[[], None]:
        """Register a subscriber. Returns an unsubscribe function."""
        with self._lock:
            self._subscribers.append(cb)

        def _unsubscribe() -> None:
            with self._lock:
                try:
                    self._subscribers.remove(cb)
                except ValueError:
                    pass

        return _unsubscribe


_tracker: FocusTracker | None = None


def get_focus_tracker() -> FocusTracker:
    global _tracker
    if _tracker is None:
        _tracker = FocusTracker()
    return _tracker
