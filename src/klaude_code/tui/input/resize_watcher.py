"""Debounced terminal-width watcher for transcript re-wrapping.

prompt-toolkit owns SIGWINCH and repaints its bottom layout on every signal,
but scrollback is hard-wrapped at the width it was printed with, so a resized
window leaves the transcript ragged. This watcher chains onto the
application's resize callback and, once the width settles, asks the runner to
repaint the transcript from the display's event tape at the new width — the
same rebuild `/refresh` and the Ctrl+O detail toggle use.

The repaint erases scrollback, which yanks a reader who has scrolled up down
to the bottom — and a viewport position can neither be queried nor restored
through the terminal protocol. So the repaint is timed instead of forced: it
runs immediately only when the user has recently pressed a key (they are at
the prompt, where the viewport already sits at the bottom); otherwise it is
parked until the next key press — the moment terminals snap the viewport to
the bottom on their own, so the repaint never moves what the user was reading.

Height-only changes never rewrap printed content, so they are ignored.
"""

from __future__ import annotations

import asyncio
import shutil
import time
from collections.abc import Callable

# One resize drag fires dozens of SIGWINCHes; a full-transcript repaint per
# signal would thrash the terminal. Repaint once, when the width stops moving.
RESIZE_SETTLE_SECONDS = 0.3

# A key press within this window means the user is engaged at the prompt, so
# the viewport is at the bottom and an immediate repaint moves nothing.
RECENT_ACTIVITY_SECONDS = 10.0


class ResizeWatcher:
    """Collapse a resize burst into one width-changed repaint, safely timed."""

    def __init__(
        self,
        on_repaint_needed: Callable[[], None],
        *,
        settle_seconds: float = RESIZE_SETTLE_SECONDS,
        recent_activity_seconds: float = RECENT_ACTIVITY_SECONDS,
    ) -> None:
        self._on_repaint_needed = on_repaint_needed
        self._settle_seconds = settle_seconds
        self._recent_activity_seconds = recent_activity_seconds
        self._last_width = self._current_width()
        self._handle: asyncio.TimerHandle | None = None
        # Launching the program counts as activity: a resize right after
        # startup repaints immediately.
        self._last_activity_at = time.monotonic()
        self._repaint_pending = False

    @staticmethod
    def _current_width() -> int:
        return shutil.get_terminal_size((120, 24)).columns

    def notify_resize(self) -> None:
        """Record a SIGWINCH; fires the settle check after the burst ends."""
        self._cancel()
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self._settle()
            return
        self._handle = loop.call_later(self._settle_seconds, self._settle)

    def notify_user_activity(self) -> None:
        """Record a key press; flushes a parked repaint at this safe moment."""
        self._last_activity_at = time.monotonic()
        if not self._repaint_pending:
            return
        self._repaint_pending = False
        self._on_repaint_needed()

    def cancel(self) -> None:
        self._cancel()
        self._repaint_pending = False

    def _cancel(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        handle.cancel()

    def _settle(self) -> None:
        self._handle = None
        width = self._current_width()
        if width == self._last_width:
            # Height-only change, or a drag that returned to the original
            # width: nothing on screen rewraps, so don't repaint.
            return
        self._last_width = width
        if time.monotonic() - self._last_activity_at <= self._recent_activity_seconds:
            self._repaint_pending = False
            self._on_repaint_needed()
            return
        # The user may be scrolled up reading; erasing scrollback now would
        # yank them to the bottom. Park the repaint until their next key press.
        self._repaint_pending = True
