"""Flicker-reduced replacement for prompt_toolkit's ``patch_stdout``.

The default ``patch_stdout`` routes scrollback writes through
``run_in_terminal``, which performs ``erase → user-write → CPR query → redraw``
sequentially. The CPR (cursor position request) round-trip leaves the bottom
prompt UI un-painted for a few milliseconds — visible as a low-frequency
flicker.

This module:

1. Wraps the entire cycle in DEC mode 2026 (``\\x1b[?2026h``/``\\x1b[?2026l``,
   "synchronized output"), so terminals that implement it present the
   intermediate frames atomically. Terminals without support silently ignore
   the codes — behavior is identical to the standard path.
2. Awaits the CPR response *inside* the synchronized block before issuing
   the redraw, so the new bottom UI lands inside the same atomic frame.
3. Bumps the StdoutProxy throttle from 0.2s to 0.5s, halving the cycle
   frequency for typical streaming workloads.

Drop-in replacement for ``patch_stdout(raw=True)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import AsyncGenerator, Generator
from typing import TextIO, cast

from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.patch_stdout import StdoutProxy

# DEC mode 2026 — synchronized output / "atomic update".
_SYNC_BEGIN = "\x1b[?2026h"
_SYNC_END = "\x1b[?2026l"

# Cap how long we wait for the CPR response inside the sync block. Modern
# terminals typically respond in <10ms; we time out conservatively so a
# misbehaving terminal can't stall the prompt.
_CPR_WAIT_TIMEOUT_S = 0.1


@contextlib.asynccontextmanager
async def synchronized_in_terminal() -> AsyncGenerator[None]:
    """Like ``prompt_toolkit.application.run_in_terminal.in_terminal`` but:

    * Wraps the full erase/write/redraw cycle in DEC 2026 synchronized output.
    * Awaits CPR response before redraw so the redraw lands inside the
      synchronized frame rather than a few ms after sync_end.

    Falls back to a plain ``yield`` when no Application is currently running,
    matching prompt_toolkit's behavior.
    """
    app = get_app_or_none()
    if app is None or not getattr(app, "_is_running", False):
        yield
        return

    # Chain after any in-progress run_in_terminal calls (mirrors prompt_toolkit).
    previous_f = app._running_in_terminal_f
    new_f: asyncio.Future[None] = asyncio.Future()
    app._running_in_terminal_f = new_f
    if previous_f is not None:
        await previous_f

    if app.output.responds_to_cpr:
        await app.renderer.wait_for_cpr_responses()

    output = app.output

    # Begin synchronized output before any visible mutation.
    _safe_write_raw(output, _SYNC_BEGIN)

    app.renderer.erase()
    app._running_in_terminal = True

    try:
        with app.input.detach(), app.input.cooked_mode():
            yield
    finally:
        try:
            app._running_in_terminal = False
            app.renderer.reset()
            app._request_absolute_cursor_position()
            # Wait for CPR inside the sync block so the subsequent redraw
            # actually paints (renderer defers render() while waiting_for_cpr
            # is set). Without this wait the redraw lands AFTER sync_end and
            # we lose the atomicity.
            if output.responds_to_cpr:
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(
                        app.renderer.wait_for_cpr_responses(timeout=1),
                        timeout=_CPR_WAIT_TIMEOUT_S,
                    )
            app._redraw()
        finally:
            _safe_write_raw(output, _SYNC_END)
            with contextlib.suppress(Exception):
                output.flush()
            if not new_f.done():
                new_f.set_result(None)


def _safe_write_raw(output: object, text: str) -> None:
    write_raw = getattr(output, "write_raw", None)
    if write_raw is None:
        return
    with contextlib.suppress(Exception):
        write_raw(text)


class FlickerSafeStdoutProxy(StdoutProxy):
    """``StdoutProxy`` variant that routes flushes through
    :func:`synchronized_in_terminal` instead of prompt_toolkit's stock
    ``run_in_terminal``.
    """

    def _write_and_flush(self, loop: asyncio.AbstractEventLoop | None, text: str) -> None:
        def write_and_flush() -> None:
            self._output.enable_autowrap()
            if self.raw:
                self._output.write_raw(text)
            else:
                self._output.write(text)
            self._output.flush()

        async def run() -> None:
            async with synchronized_in_terminal():
                write_and_flush()

        if loop is None:
            write_and_flush()
        else:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(run()))


@contextlib.contextmanager
def flicker_safe_patch_stdout(
    *,
    raw: bool = True,
    sleep_between_writes: float = 0.5,
) -> Generator[None]:
    """Drop-in replacement for ``prompt_toolkit.patch_stdout.patch_stdout``.

    Defaults differ from prompt_toolkit:

    * ``raw=True`` — Rich emits ANSI directly; we never want it stripped.
    * ``sleep_between_writes=0.5`` — bump from prompt_toolkit's 0.2s to halve
      the cycle frequency during streaming. Stable scrollback text appears
      in slightly larger chunks (every ~0.5s) but with materially less
      flicker.
    """
    proxy = FlickerSafeStdoutProxy(sleep_between_writes=sleep_between_writes, raw=raw)
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = cast(TextIO, proxy)
    sys.stderr = cast(TextIO, proxy)
    try:
        yield
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        proxy.close()
