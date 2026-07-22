# pyright: reportPrivateUsage=false

import asyncio
import fcntl
import os
import time
from types import SimpleNamespace


def test_synchronized_in_terminal_no_app_yields_cleanly() -> None:
    """When no prompt-toolkit Application is running we must transparently
    no-op so non-interactive paths (replay, headless tests) keep working."""
    from klaude_code.tui.input.flicker_safe_stdout import synchronized_in_terminal

    entered = False

    async def _run() -> None:
        nonlocal entered
        async with synchronized_in_terminal():
            entered = True

    asyncio.run(_run())
    assert entered is True


def test_flicker_safe_proxy_constructs_with_raw_default() -> None:
    """Sanity: defaults are raw=True (Rich ANSI passes through) and the
    bumped throttle is honored."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)
    try:
        assert proxy.raw is True
        assert proxy.sleep_between_writes == 0.5
    finally:
        proxy.close()


def test_synchronized_in_terminal_times_out_stale_cpr(monkeypatch) -> None:
    """A stale CPR wait must not block the first scrollback write after submit.

    On timeout the pending CPR futures must be left intact (not cancelled,
    not cleared) so a late response is still attributed FIFO to the request
    that triggered it.
    """

    from collections import deque

    import klaude_code.tui.input.flicker_safe_stdout as module

    class _FakeRenderer:
        def __init__(self) -> None:
            self._waiting_for_cpr_futures: deque[asyncio.Future[None]] = deque()

        def erase(self) -> None:
            return None

        def reset(self) -> None:
            return None

    class _FakeOutput:
        responds_to_cpr = True

        def write_raw(self, _text: str) -> None:
            return None

        def flush(self) -> None:
            return None

    renderer = _FakeRenderer()
    app = SimpleNamespace(
        _is_running=True,
        _running_in_terminal_f=None,
        _running_in_terminal=False,
        output=_FakeOutput(),
        renderer=renderer,
        _request_absolute_cursor_position=lambda: None,
        _redraw=lambda: None,
    )
    monkeypatch.setattr(module, "get_app_or_none", lambda: app)
    monkeypatch.setattr(module, "_CPR_WAIT_TIMEOUT_S", 0.01)

    entered = False

    async def _run() -> None:
        nonlocal entered
        stale: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        renderer._waiting_for_cpr_futures.append(stale)
        async with module.synchronized_in_terminal():
            entered = True
        assert not stale.cancelled()
        assert renderer._waiting_for_cpr_futures

    asyncio.run(asyncio.wait_for(_run(), timeout=0.2))
    assert entered is True


def test_flicker_safe_patch_stdout_swaps_streams() -> None:
    """Using the context manager replaces sys.stdout/stderr while active and
    restores them on exit."""
    import sys

    from klaude_code.tui.input.flicker_safe_stdout import (
        FlickerSafeStdoutProxy,
        flicker_safe_patch_stdout,
    )

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    with flicker_safe_patch_stdout():
        assert isinstance(sys.stdout, FlickerSafeStdoutProxy)
        assert sys.stderr is sys.stdout
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr


def test_settle_flicker_safe_stdout_returns_when_no_pending_work() -> None:
    """When there are no buffered writes, settle returns promptly. This is
    the common case at the runner sync points and must not hang."""
    from klaude_code.tui.input.flicker_safe_stdout import (
        FlickerSafeStdoutProxy,
        settle_flicker_safe_stdout,
    )

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        # Without a patched sys.stdout, settle is a no-op.
        await settle_flicker_safe_stdout()

        # Even with the proxy installed, an empty queue + no in-flight
        # futures returns straight away.
        try:
            import sys

            original = sys.stdout
            sys.stdout = proxy  # type: ignore[assignment]
            try:
                await settle_flicker_safe_stdout(timeout=0.5)
            finally:
                sys.stdout = original
        finally:
            proxy.close()

    asyncio.run(_scenario())


def test_wait_for_pending_writes_drains_in_flight_futures() -> None:
    """When in-flight in_terminal futures exist, wait_for_pending_writes
    awaits them. We simulate this by putting a completed future into the
    pending set; the wait should resolve."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[None] = loop.create_future()
        with proxy._pending_lock:
            proxy._pending_in_terminal.add(future)

        async def _resolve_after_yield() -> None:
            await asyncio.sleep(0)
            if not future.done():
                future.set_result(None)

        resolve_task = loop.create_task(_resolve_after_yield())
        await proxy.wait_for_pending_writes(timeout=1.0)
        await resolve_task
        assert future.done()

    try:
        asyncio.run(_scenario())
    finally:
        proxy.close()


def test_wait_for_pending_writes_timeout_does_not_cancel_in_flight_future() -> None:
    """Timeout stops waiting but leaves the real terminal write task alive."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        loop = asyncio.get_event_loop()
        future: asyncio.Future[None] = loop.create_future()
        with proxy._pending_lock:
            proxy._pending_in_terminal.add(future)

        await proxy.wait_for_pending_writes(timeout=0.01)

        assert not future.done()
        assert not future.cancelled()
        future.set_result(None)

    try:
        asyncio.run(_scenario())
    finally:
        proxy.close()


def test_split_write_frames_small_text_single_frame() -> None:
    """The common streaming case (small flush) must stay a single cycle."""
    from klaude_code.tui.input.flicker_safe_stdout import _split_write_frames

    text = "line one\nline two\n"
    assert _split_write_frames(text, max_chars=100) == [text]


def test_split_write_frames_breaks_on_line_boundaries() -> None:
    """Large payloads split into line-aligned frames that rejoin losslessly:
    the redraw between cycles paints the bottom UI at the cursor row, so no
    frame may end mid-line."""
    from klaude_code.tui.input.flicker_safe_stdout import _split_write_frames

    lines = [f"line {i:04d} with some padding text\n" for i in range(100)]
    text = "".join(lines)
    frames = _split_write_frames(text, max_chars=200)

    assert len(frames) > 1
    assert "".join(frames) == text
    for frame in frames[:-1]:
        assert frame.endswith("\n")
        assert len(frame) <= 200


def test_split_write_frames_keeps_oversized_line_whole() -> None:
    """A single line longer than the cap must not split mid-line (and thus
    mid-escape-sequence at a frame boundary)."""
    from klaude_code.tui.input.flicker_safe_stdout import _split_write_frames

    huge = "x" * 500
    text = f"short\n{huge}\nshort\n"
    frames = _split_write_frames(text, max_chars=100)

    assert "".join(frames) == text
    assert any(huge in frame for frame in frames)


def test_write_fd_nonblocking_keeps_loop_alive_under_backpressure() -> None:
    """Writing a payload much larger than the pipe buffer against a slow
    reader must not block the event loop: a concurrent ticker task has to
    keep running while the drain is in progress, and every byte must arrive
    intact. This is the regression test for the mid-write loop freeze
    (queue box disappearing / frozen spinner during large tool results)."""
    import klaude_code.tui.input.flicker_safe_stdout as module

    read_fd, write_fd = os.pipe()
    payload = bytes(range(256)) * 4096  # 1 MiB, far beyond the pipe buffer
    received = bytearray()
    ticks = 0

    async def _scenario() -> None:
        nonlocal ticks
        loop = asyncio.get_running_loop()

        async def _ticker() -> None:
            nonlocal ticks
            while True:
                ticks += 1
                await asyncio.sleep(0.005)

        def _slow_drain() -> None:
            while len(received) < len(payload):
                time.sleep(0.002)
                received.extend(os.read(read_fd, 65536))

        ticker = asyncio.create_task(_ticker())
        drain = loop.run_in_executor(None, _slow_drain)
        try:
            await module._write_fd_nonblocking(write_fd, payload)
            await drain
        finally:
            ticker.cancel()

    try:
        asyncio.run(asyncio.wait_for(_scenario(), timeout=10.0))
        assert bytes(received) == payload
        # A blocking write would freeze the loop for the whole drain
        # (ticks stays 0-1); the non-blocking path keeps it running.
        assert ticks >= 3
        # The fd must be left blocking (macOS F_GETFL reports extra
        # kernel-internal bits, so compare the O_NONBLOCK bit only).
        assert not (fcntl.fcntl(write_fd, fcntl.F_GETFL) & os.O_NONBLOCK)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_flush_output_nonblocking_writes_buffer_through_fd() -> None:
    """With a Vt100-shaped output the buffer is drained via the fd and
    cleared, exactly like the stock flush but loop-friendly."""
    import klaude_code.tui.input.flicker_safe_stdout as module

    read_fd, write_fd = os.pipe()

    class _Vt100Like:
        def __init__(self) -> None:
            self._buffer: list[str] = ["hello ", "world\n"]

        def fileno(self) -> int:
            return write_fd

        def encoding(self) -> str:
            return "utf-8"

        def flush(self) -> None:
            raise AssertionError("blocking flush must not be used on the fd path")

    output = _Vt100Like()
    try:
        asyncio.run(module._flush_output_nonblocking(output))
        assert output._buffer == []
        assert os.read(read_fd, 1024) == b"hello world\n"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_flush_output_nonblocking_falls_back_without_fd() -> None:
    """Outputs without Vt100 internals (plain-text outputs in tests) must
    fall back to the stock blocking flush with the buffer intact."""
    import klaude_code.tui.input.flicker_safe_stdout as module

    flushed = False

    class _PlainOutput:
        def __init__(self) -> None:
            self._buffer: list[str] = ["content"]

        def fileno(self) -> int:
            raise OSError("no fd")

        def encoding(self) -> str:
            return "utf-8"

        def flush(self) -> None:
            nonlocal flushed
            flushed = True

    output = _PlainOutput()
    asyncio.run(module._flush_output_nonblocking(output))
    assert flushed is True
    assert output._buffer == ["content"]


def test_wait_for_pending_writes_waits_for_thread_handoff() -> None:
    """A flush item can be off the queue before its future is registered;
    settle must still wait for that handoff to finish."""
    from klaude_code.tui.input.flicker_safe_stdout import FlickerSafeStdoutProxy

    proxy = FlickerSafeStdoutProxy(sleep_between_writes=0.5, raw=True)

    async def _scenario() -> None:
        loop = asyncio.get_event_loop()
        with proxy._pending_lock:
            proxy._active_write_handoffs += 1

        async def _finish_handoff() -> None:
            await asyncio.sleep(0.02)
            with proxy._pending_lock:
                proxy._active_write_handoffs -= 1

        start = loop.time()
        handoff_task = loop.create_task(_finish_handoff())
        await proxy.wait_for_pending_writes(timeout=1.0)
        await handoff_task

        assert loop.time() - start >= 0.02

    try:
        asyncio.run(_scenario())
    finally:
        proxy.close()


def test_renderer_flush_guard_parks_tail_and_drains_when_writable() -> None:
    """A renderer flush into a full pipe must return immediately (loop stays
    alive), park the unwritten tail, mark it via tty_state, and finish the
    write once the reader drains — with byte order preserved."""
    import klaude_code.tui.input.flicker_safe_stdout as module
    from klaude_code.tui.terminal import tty_state

    read_fd, write_fd = os.pipe()
    # Fill the pipe so the first non-blocking write cannot complete.
    os.set_blocking(write_fd, False)
    preload = 0
    try:
        while True:
            preload += os.write(write_fd, b"x" * 4096)
    except BlockingIOError:
        pass
    os.set_blocking(write_fd, True)

    frame = "F" * 8192

    class _Vt100Like:
        def __init__(self) -> None:
            self._buffer: list[str] = [frame]

        def fileno(self) -> int:
            return write_fd

        def encoding(self) -> str:
            return "utf-8"

        def flush(self) -> None:
            raise AssertionError("guard must not fall back to the blocking flush here")

    output = _Vt100Like()
    received = bytearray()

    async def _scenario() -> None:
        loop = asyncio.get_running_loop()
        guard = module.RendererFlushGuard(output)
        guard.install()
        started = loop.time()
        output.flush()
        # The flush returned without blocking on the full pipe.
        assert loop.time() - started < 1.0
        assert tty_state.renderer_tail_pending()
        assert output._buffer == []

        def _drain_all() -> None:
            target = preload + len(frame)
            while len(received) < target:
                time.sleep(0.001)
                received.extend(os.read(read_fd, 65536))

        await loop.run_in_executor(None, _drain_all)
        # Give the loop writer callback a few iterations to finish the tail.
        for _ in range(100):
            if not tty_state.renderer_tail_pending():
                break
            await asyncio.sleep(0.01)
        assert not tty_state.renderer_tail_pending()

    try:
        asyncio.run(asyncio.wait_for(_scenario(), timeout=10.0))
        assert bytes(received[preload:]) == frame.encode()
    finally:
        tty_state.set_renderer_tail_pending(False)
        os.close(read_fd)
        os.close(write_fd)


def test_renderer_flush_guard_writes_through_when_unobstructed() -> None:
    """With room in the pipe the guard behaves like the stock flush: bytes
    land immediately and no tail is parked."""
    import klaude_code.tui.input.flicker_safe_stdout as module
    from klaude_code.tui.terminal import tty_state

    read_fd, write_fd = os.pipe()

    class _Vt100Like:
        def __init__(self) -> None:
            self._buffer: list[str] = ["prompt line\n"]

        def fileno(self) -> int:
            return write_fd

        def encoding(self) -> str:
            return "utf-8"

        def flush(self) -> None:
            raise AssertionError("unexpected blocking flush")

    output = _Vt100Like()

    async def _scenario() -> None:
        guard = module.RendererFlushGuard(output)
        guard.install()
        output.flush()
        assert not tty_state.renderer_tail_pending()

    try:
        asyncio.run(_scenario())
        assert os.read(read_fd, 1024) == b"prompt line\n"
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_scrollback_cycle_flag_blocks_raw_writers() -> None:
    """scrollback_write_in_flight() must cover the whole cycle window and
    the renderer-tail window so title/notifier raw writes stay out."""
    from klaude_code.tui.terminal import tty_state

    assert not tty_state.scrollback_write_in_flight()
    tty_state.push_scrollback_cycle()
    try:
        assert tty_state.scrollback_write_in_flight()
    finally:
        tty_state.pop_scrollback_cycle()
    assert not tty_state.scrollback_write_in_flight()

    tty_state.set_renderer_tail_pending(True)
    try:
        assert tty_state.scrollback_write_in_flight()
    finally:
        tty_state.set_renderer_tail_pending(False)
    assert not tty_state.scrollback_write_in_flight()
