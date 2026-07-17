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
4. Keeps the input attached during the write cycle (stock ``in_terminal``
   detaches stdin and enters cooked mode, which stalls key processing for
   the whole erase/write/redraw window). The body only writes, so yielding
   stdin is unnecessary and typing stays responsive while streaming.
5. Keeps the cursor hidden for the whole erase/write/redraw cycle.
   ``Renderer.erase``/``reset`` re-show the cursor, so on terminals without
   DEC 2026 it visibly jumps between the scrollback write position and the
   redrawn prompt. The final redraw restores visibility from screen state.

Drop-in replacement for ``patch_stdout(raw=True)``.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import threading
from collections.abc import AsyncGenerator, Generator
from typing import TextIO, cast

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.patch_stdout import StdoutProxy

# DEC mode 2026 — synchronized output / "atomic update".
_SYNC_BEGIN = "\x1b[?2026h"
_SYNC_END = "\x1b[?2026l"

# Cap how long we wait for the CPR response inside the sync block. Modern
# terminals typically respond in <10ms; we time out conservatively so a
# misbehaving terminal can't stall the prompt. Keep this short: while a
# write cycle is in flight the renderer defers redraws, so every ms spent
# here delays the next visible frame (though key events keep flowing).
_CPR_WAIT_TIMEOUT_S = 0.05


async def _await_cpr_responses(app: Application[object], timeout: float) -> None:
    """Wait briefly for pending CPR responses, preserving renderer state.

    ``Renderer.wait_for_cpr_responses`` spawns an internal timeout task that,
    when it fires, cancels the futures it snapshotted and replaces the
    renderer's whole pending deque. Wrapping that call in ``asyncio.wait_for``
    leaks the timeout task on early cancellation, so up to a second later it
    wipes CPR futures belonging to a *later* write cycle. That desyncs
    response attribution and feeds the renderer wrong height estimates —
    visible as the bottom UI jumping while an agent streams. Wait on a
    snapshot instead and leave the deque untouched on timeout; late responses
    still resolve their futures in FIFO order.
    """
    renderer = app.renderer
    pending = renderer._waiting_for_cpr_futures
    # Safety valve: a terminal that advertises CPR support but stops
    # responding would otherwise grow the deque by one future per cycle.
    while len(pending) > 8:
        pending.popleft().cancel()
    futures = [future for future in pending if not future.done()]
    if not futures:
        return
    with contextlib.suppress(Exception):
        await asyncio.wait(futures, timeout=timeout)


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

    # Drain any outstanding CPR response before erasing, so a late reply to
    # the previous redraw's request is not attributed to the request we issue
    # after this cycle's reset. Input stays attached, so the response is
    # consumed by the vt100 parser as soon as it arrives.
    if app.output.responds_to_cpr:
        await _await_cpr_responses(app, _CPR_WAIT_TIMEOUT_S)

    output = app.output

    # Begin synchronized output before any visible mutation.
    _safe_write_raw(output, _SYNC_BEGIN)

    app.renderer.erase()
    # erase() ends with reset(), which re-shows the cursor. Keep it hidden
    # for the rest of the cycle; the closing redraw restores visibility from
    # the rendered screen state.
    _safe_hide_cursor(output)
    app._running_in_terminal = True

    try:
        # Unlike prompt_toolkit's stock ``in_terminal`` we do NOT detach the
        # input or enter cooked mode: the body only writes to stdout, never
        # reads stdin. Keeping the reader attached lets key presses be
        # processed (buffer updates, key bindings) during the write cycle
        # instead of piling up in the tty buffer — detaching here was the
        # main source of typing latency while the agent streamed output.
        # ``Application._redraw`` already defers rendering while
        # ``_running_in_terminal`` is set, so there is no paint race.
        yield
    finally:
        try:
            app._running_in_terminal = False
            app.renderer.reset()
            _safe_hide_cursor(output)
            app._request_absolute_cursor_position()
            # Wait for CPR inside the sync block so the subsequent redraw
            # actually paints (renderer defers render() while waiting_for_cpr
            # is set). Without this wait the redraw lands AFTER sync_end and
            # we lose the atomicity.
            if output.responds_to_cpr:
                await _await_cpr_responses(app, _CPR_WAIT_TIMEOUT_S)
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


def _safe_hide_cursor(output: object) -> None:
    hide_cursor = getattr(output, "hide_cursor", None)
    if hide_cursor is None:
        return
    with contextlib.suppress(Exception):
        hide_cursor()


class FlickerSafeStdoutProxy(StdoutProxy):
    """``StdoutProxy`` variant that routes flushes through
    :func:`synchronized_in_terminal` instead of prompt_toolkit's stock
    ``run_in_terminal``. Tracks in-flight write futures so callers can
    enforce ordering against scrollback content (see
    :meth:`wait_for_pending_writes`).
    """

    def __init__(self, sleep_between_writes: float = 0.2, raw: bool = False) -> None:
        super().__init__(sleep_between_writes=sleep_between_writes, raw=raw)
        self._pending_in_terminal: set[asyncio.Future[None]] = set()
        self._pending_lock = threading.Lock()
        self._active_write_handoffs = 0

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
            return

        with self._pending_lock:
            self._active_write_handoffs += 1

        def schedule() -> None:
            try:
                future = asyncio.ensure_future(run())
                with self._pending_lock:
                    self._pending_in_terminal.add(future)
                    self._active_write_handoffs -= 1
                future.add_done_callback(self._discard_pending_future)
            except Exception:
                with self._pending_lock:
                    self._active_write_handoffs -= 1
                raise

        try:
            loop.call_soon_threadsafe(schedule)
        except Exception:
            with self._pending_lock:
                self._active_write_handoffs -= 1
            raise

    def _discard_pending_future(self, future: asyncio.Future[None]) -> None:
        with self._pending_lock:
            self._pending_in_terminal.discard(future)

    def _pending_snapshot(self) -> tuple[int, list[asyncio.Future[None]]]:
        with self._pending_lock:
            self._pending_in_terminal = {future for future in self._pending_in_terminal if not future.done()}
            return self._active_write_handoffs, list(self._pending_in_terminal)

    async def wait_for_pending_writes(self, *, timeout: float = 2.0) -> None:
        """Block until every queued Rich write has been dispatched and
        the resulting ``synchronized_in_terminal`` coroutines have
        completed.

        Used at sync points (e.g. before emitting a queued follow-up
        ``UserMessageEvent``) to guarantee that the previous task's
        scrollback content is fully painted before the next event lands.

        The method:

        1. Pushes the proxy's per-line buffer into the flush queue so no
           partial line lingers.
        2. Polls until the flush thread's queue is empty AND no
           in-flight ``synchronized_in_terminal`` futures remain.
        3. Awaits the in-flight futures so the caller is suspended only
           while real work is pending.

        ``timeout`` caps the wait; if reached we return early to avoid
        hanging the prompt on a misbehaving terminal.
        """
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        # Force any partial-line buffer through to the flush thread.
        with contextlib.suppress(Exception):
            self.flush()
        while True:
            queue_empty = self._flush_queue.empty()
            active_handoffs, futures_pending = self._pending_snapshot()
            if queue_empty and active_handoffs == 0 and not futures_pending:
                return
            if loop.time() >= deadline:
                return
            if futures_pending:
                await asyncio.wait(futures_pending, timeout=max(0.01, deadline - loop.time()))
            # Yield so the flush thread's `call_soon_threadsafe` schedule
            # callback can land on the loop and create a new future, or
            # so a still-buffered partial line gets flushed.
            await asyncio.sleep(0.01)


async def settle_flicker_safe_stdout(*, timeout: float = 2.0) -> None:
    """If the active ``sys.stdout`` is a :class:`FlickerSafeStdoutProxy`,
    wait for all queued Rich writes to be dispatched and the resulting
    in_terminal cycles to finish.

    Safe to call from anywhere; no-op when stdout has not been patched
    or when the active proxy is a different type.
    """
    proxy = sys.stdout
    if isinstance(proxy, FlickerSafeStdoutProxy):
        await proxy.wait_for_pending_writes(timeout=timeout)


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
