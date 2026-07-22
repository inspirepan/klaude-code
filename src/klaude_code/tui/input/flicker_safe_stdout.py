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
import fcntl
import os
import sys
import threading
from collections.abc import AsyncGenerator, Callable, Generator
from typing import Any, TextIO, cast

from prompt_toolkit.application import Application
from prompt_toolkit.application.current import get_app_or_none
from prompt_toolkit.patch_stdout import StdoutProxy

from klaude_code.tui.terminal import tty_state
from klaude_code.tui.terminal.tty_state import stdout_writable

# DEC mode 2026 — synchronized output / "atomic update".
_SYNC_BEGIN = "\x1b[?2026h"
_SYNC_END = "\x1b[?2026l"

# Cap how long we wait for the CPR response inside the sync block. Modern
# terminals typically respond in <10ms; we time out conservatively so a
# misbehaving terminal can't stall the prompt. Keep this short: while a
# write cycle is in flight the renderer defers redraws, so every ms spent
# here delays the next visible frame (though key events keep flowing).
_CPR_WAIT_TIMEOUT_S = 0.05

# When the terminal stops draining the pty (occluded window, renderer stall),
# hold the write cycle in an awaitable wait instead of letting the erase/write
# block the event loop. Capped so a permanently wedged terminal still makes
# (blocking) progress eventually rather than buffering output forever.
_TTY_WRITABLE_POLL_INTERVAL_S = 0.05
_TTY_WRITABLE_WAIT_MAX_S = 30.0

# Cap the scrollback payload written inside a single erase/write/redraw
# cycle. A large tool result (diff, bash output) written as one frame keeps
# the bottom UI erased — and the DEC 2026 frame open — for the whole drain,
# so a slow terminal presents the erased state (input box and queue list
# gone). Splitting on line boundaries restores the bottom UI between frames
# and keeps each synchronized frame short.
_FRAME_MAX_CHARS = 8192


async def _wait_for_tty_writable() -> None:
    if stdout_writable():
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TTY_WRITABLE_WAIT_MAX_S
    while loop.time() < deadline:
        await asyncio.sleep(_TTY_WRITABLE_POLL_INTERVAL_S)
        if stdout_writable():
            return


async def _wait_for_renderer_tail_drained() -> None:
    """Hold until any partially-written renderer frame finishes draining.

    A write cycle starting while a renderer flush tail is pending would
    interleave the erase sequence into the middle of that frame's escape
    sequences. The tail drains via a loop writer callback; give up after
    the shared deadline and force it out blockingly so a wedged terminal
    still makes progress.
    """
    if not tty_state.renderer_tail_pending():
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TTY_WRITABLE_WAIT_MAX_S
    while loop.time() < deadline:
        await asyncio.sleep(_TTY_WRITABLE_POLL_INTERVAL_S)
        if not tty_state.renderer_tail_pending():
            return
    drain_renderer_tail_blocking()


def _split_write_frames(text: str, max_chars: int = _FRAME_MAX_CHARS) -> list[str]:
    """Split a coalesced scrollback payload into per-cycle frames.

    Frames break only on line boundaries: the redraw between cycles paints
    the bottom UI at the cursor row, so a frame must not end mid-line. A
    single line longer than ``max_chars`` stays whole (the non-blocking
    drain still protects the event loop for oversized frames).
    """
    if len(text) <= max_chars:
        return [text]
    frames: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if current and current_len + len(line) > max_chars:
            frames.append("".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line)
    if current:
        frames.append("".join(current))
    return frames


def _write_fd_blocking(fd: int, view: memoryview, offset: int) -> None:
    """Write the remainder of ``view`` with a blocking fd, restoring flags."""
    old_flags: int | None
    try:
        old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
        fcntl.fcntl(fd, fcntl.F_SETFL, old_flags & ~os.O_NONBLOCK)
    except OSError:
        old_flags = None
    try:
        while offset < len(view):
            offset += os.write(fd, view[offset:])
    finally:
        if old_flags is not None:
            with contextlib.suppress(OSError):
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)


async def _write_fd_nonblocking(fd: int, payload: bytes) -> None:
    """Write ``payload`` to ``fd`` without ever blocking the event loop.

    ``stdout_writable()`` before a cycle only proves the pty buffer has
    *some* room; a multi-KB payload can still block mid-write when the
    terminal drains slowly — with the bottom UI already erased. Toggle
    ``O_NONBLOCK`` around each ``os.write`` so partial writes return
    immediately, and yield to the loop between attempts. After
    ``_TTY_WRITABLE_WAIT_MAX_S`` (or if flag manipulation fails) fall back
    to a blocking write so a wedged terminal still makes progress
    eventually instead of buffering output forever.
    """
    view = memoryview(payload)
    offset = 0
    total = len(view)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _TTY_WRITABLE_WAIT_MAX_S
    while offset < total:
        try:
            old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
            try:
                written = os.write(fd, view[offset:])
            except BlockingIOError:
                written = 0
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
        except OSError:
            break
        offset += written
        if offset >= total:
            return
        if written == 0:
            if loop.time() >= deadline:
                break
            await asyncio.sleep(_TTY_WRITABLE_POLL_INTERVAL_S)
    _write_fd_blocking(fd, view, offset)


async def _flush_output_nonblocking(output: object) -> None:
    """Drain the prompt_toolkit output buffer without blocking the loop.

    Mirrors ``Vt100_Output.flush`` (join ``_buffer``, encode with
    ``replace``) but hands the bytes to :func:`_write_fd_nonblocking`.
    Falls back to the stock blocking ``flush()`` when the output does not
    have the expected Vt100 shape (plain-text outputs in tests, no fd).
    """
    buffer = getattr(output, "_buffer", None)
    flush = getattr(output, "flush", None)

    def _flush_blocking() -> None:
        if flush is not None:
            with contextlib.suppress(Exception):
                flush()

    if not isinstance(buffer, list) or not buffer:
        _flush_blocking()
        return
    fileno = getattr(output, "fileno", None)
    get_encoding = getattr(output, "encoding", None)
    if fileno is None or get_encoding is None:
        _flush_blocking()
        return
    try:
        fd = int(fileno())
        encoding = str(get_encoding() or "utf-8")
    except Exception:
        _flush_blocking()
        return
    data = "".join(buffer)
    buffer.clear()
    await _write_fd_nonblocking(fd, data.encode(encoding, "replace"))


# Cap the renderer-tail buffer. Under a stalled tty pt keeps rendering
# (key presses append a few KB per frame); past this we drain blockingly —
# the old behavior — rather than buffer without bound.
_RENDERER_TAIL_MAX_BYTES = 1024 * 1024

_renderer_flush_guard: RendererFlushGuard | None = None


class RendererFlushGuard:
    """Make prompt_toolkit renderer flushes non-blocking under tty backpressure.

    ``Renderer.render`` ends with a synchronous ``output.flush()`` straight
    into fd 1; when the terminal stops draining the pty, a key-press redraw
    freezes the whole event loop. This wraps the app output's ``flush``:
    outside write cycles it drains what it can with ``O_NONBLOCK`` and
    parks the unwritten tail on a loop writer callback. Ordering is
    preserved — later flushes append to the tail — and cross-writer safety
    is handled by ``tty_state.renderer_tail_pending`` (title/notifier skip,
    write cycles await the drain).
    """

    def __init__(self, output: Any) -> None:
        self._output = output
        self._orig_flush: Callable[[], None] = output.flush
        self._pending = bytearray()
        self._writer_fd: int | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def install(self) -> None:
        self._output.flush = self._flush

    def _take_buffered_bytes(self) -> bytes:
        buffer = getattr(self._output, "_buffer", None)
        if not isinstance(buffer, list) or not buffer:
            return b""
        data = "".join(cast("list[str]", buffer))
        buffer.clear()
        get_encoding = getattr(self._output, "encoding", None)
        encoding = "utf-8"
        if get_encoding is not None:
            with contextlib.suppress(Exception):
                encoding = str(get_encoding() or "utf-8")
        return data.encode(encoding, "replace")

    def _flush(self) -> None:
        if tty_state.scrollback_write_in_flight() and not self._pending:
            # Inside a write cycle ordering relies on sequential blocking
            # writes (cycle start already ensured writability + tail drain).
            self._orig_flush()
            return
        try:
            fd = int(self._output.fileno())
            loop = asyncio.get_running_loop()
        except Exception:
            self._orig_flush()
            return
        self._pending.extend(self._take_buffered_bytes())
        if not self._pending:
            return
        self._loop = loop
        self._drain(fd)

    def _drain(self, fd: int) -> None:
        try:
            while self._pending:
                old_flags = fcntl.fcntl(fd, fcntl.F_GETFL)
                fcntl.fcntl(fd, fcntl.F_SETFL, old_flags | os.O_NONBLOCK)
                try:
                    written = os.write(fd, self._pending)
                except BlockingIOError:
                    written = 0
                finally:
                    fcntl.fcntl(fd, fcntl.F_SETFL, old_flags)
                if written == 0:
                    break
                del self._pending[:written]
        except OSError:
            # Flag manipulation or write failed; degrade to the blocking path.
            self._drain_blocking(fd)
            return
        if not self._pending:
            self._unpark(fd)
            return
        if len(self._pending) > _RENDERER_TAIL_MAX_BYTES:
            self._drain_blocking(fd)
            return
        self._park(fd)

    def _park(self, fd: int) -> None:
        tty_state.set_renderer_tail_pending(True)
        if self._writer_fd is not None or self._loop is None:
            return
        try:
            self._loop.add_writer(fd, self._drain, fd)
            self._writer_fd = fd
        except (NotImplementedError, OSError):
            self._drain_blocking(fd)

    def _unpark(self, fd: int) -> None:
        if self._writer_fd is not None and self._loop is not None:
            with contextlib.suppress(Exception):
                self._loop.remove_writer(self._writer_fd)
            self._writer_fd = None
        tty_state.set_renderer_tail_pending(False)

    def _drain_blocking(self, fd: int) -> None:
        pending = bytes(self._pending)
        self._pending.clear()
        self._unpark(fd)
        if pending:
            with contextlib.suppress(OSError):
                _write_fd_blocking(fd, memoryview(pending), 0)

    def drain_blocking(self) -> None:
        """Force any parked tail out with blocking writes (teardown/fallback)."""
        try:
            fd = int(self._output.fileno())
        except Exception:
            self._pending.clear()
            tty_state.set_renderer_tail_pending(False)
            return
        self._drain_blocking(fd)


def install_renderer_flush_guard(output: Any) -> None:
    """Idempotently wrap ``output.flush`` with the non-blocking guard."""
    global _renderer_flush_guard
    if _renderer_flush_guard is not None and _renderer_flush_guard._output is output:
        return
    guard = RendererFlushGuard(output)
    guard.install()
    _renderer_flush_guard = guard


def drain_renderer_tail_blocking() -> None:
    if _renderer_flush_guard is not None:
        _renderer_flush_guard.drain_blocking()


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
        # No app: writes below go straight to fd 1. Flush any parked
        # renderer tail first so they don't land mid-escape-sequence.
        if tty_state.renderer_tail_pending():
            drain_renderer_tail_blocking()
        yield
        return

    # Chain after any in-progress run_in_terminal calls (mirrors prompt_toolkit).
    previous_f = app._running_in_terminal_f
    new_f: asyncio.Future[None] = asyncio.Future()
    app._running_in_terminal_f = new_f
    if previous_f is not None:
        await previous_f

    # Hold the cycle while the terminal is not draining the pty. The erase
    # and body writes below are synchronous fd-1 writes; issuing them into a
    # full buffer would block the whole event loop (display, LLM stream)
    # instead of just delaying this frame. Ordering is safe: later cycles
    # chain behind this one via app._running_in_terminal_f.
    await _wait_for_tty_writable()
    # A partially-drained renderer frame must finish before the erase below,
    # or the erase sequence lands mid-escape.
    await _wait_for_renderer_tail_drained()

    # Drain any outstanding CPR response before erasing, so a late reply to
    # the previous redraw's request is not attributed to the request we issue
    # after this cycle's reset. Input stays attached, so the response is
    # consumed by the vt100 parser as soon as it arrives.
    if app.output.responds_to_cpr:
        await _await_cpr_responses(app, _CPR_WAIT_TIMEOUT_S)

    output = app.output

    # Mark the WHOLE cycle (erase through closing redraw) so raw fd-1
    # writers skip it and the wrapped renderer flush stays blocking inside.
    tty_state.push_scrollback_cycle()

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
            # The redraw paints the full bottom UI (a few KB) through a
            # blocking flush; hold it while the pty buffer has zero room so
            # a stalled terminal can't freeze the loop right at cycle end.
            await _wait_for_tty_writable()
            app._redraw()
        finally:
            _safe_write_raw(output, _SYNC_END)
            with contextlib.suppress(Exception):
                output.flush()
            tty_state.pop_scrollback_cycle()
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
        def _buffer_frame(frame: str) -> None:
            self._output.enable_autowrap()
            if self.raw:
                self._output.write_raw(frame)
            else:
                self._output.write(frame)

        async def run(frame: str) -> None:
            async with synchronized_in_terminal():
                _buffer_frame(frame)
                # Drain via non-blocking fd writes: the bottom UI is erased
                # at this point, and a blocking flush into a slow-draining
                # terminal would freeze the loop (spinner, display consumer,
                # LLM stream) with the UI torn down.
                await _flush_output_nonblocking(self._output)

        if loop is None:
            _buffer_frame(text)
            self._output.flush()
            return

        with self._pending_lock:
            self._active_write_handoffs += 1

        def schedule() -> None:
            try:
                # One erase/write/redraw cycle per frame; cycles chain via
                # app._running_in_terminal_f, and tasks created in order run
                # their synchronous prologue in order, so frames stay FIFO.
                futures = [asyncio.ensure_future(run(frame)) for frame in _split_write_frames(text)]
                with self._pending_lock:
                    self._pending_in_terminal.update(futures)
                    self._active_write_handoffs -= 1
                for future in futures:
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
