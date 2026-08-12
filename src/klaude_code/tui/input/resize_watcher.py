"""Debounced terminal-width watcher for transcript re-wrapping.

prompt-toolkit owns SIGWINCH and repaints its bottom layout on every signal,
but scrollback is hard-wrapped at the width it was printed with, so a resized
window leaves the transcript ragged. This watcher chains onto the
application's resize callback and, once the width settles, asks the runner to
repaint the transcript from the display's event tape at the new width — the
same rebuild `/refresh` and the Ctrl+O detail toggle use.

The repaint erases scrollback and moves the terminal viewport to the bottom.
The repaint runs after the resize burst settles, regardless of recent user
activity, so the transcript always rewraps as soon as the new width is known.

Height-only changes never rewrap printed content, so they are ignored.
"""

from __future__ import annotations

import asyncio
import shutil
from collections.abc import Callable

# One resize drag fires dozens of SIGWINCHes; a full-transcript repaint per
# signal would thrash the terminal. Repaint once, when the width stops moving.
RESIZE_SETTLE_SECONDS = 0.3


class ResizeWatcher:
    """Collapse a resize burst into one width-changed repaint."""

    def __init__(
        self,
        on_repaint_needed: Callable[[], None],
        *,
        settle_seconds: float = RESIZE_SETTLE_SECONDS,
    ) -> None:
        self._on_repaint_needed = on_repaint_needed
        self._settle_seconds = settle_seconds
        self._last_width = self._current_width()
        self._handle: asyncio.TimerHandle | None = None

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

    def cancel(self) -> None:
        self._cancel()

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
        self._on_repaint_needed()
