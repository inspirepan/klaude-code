import asyncio
import contextlib
import os
import select
import signal
import sys
import termios
import threading
import tty
from collections.abc import Callable, Coroutine
from types import FrameType
from typing import Any

from klaude_code.log import log


def start_esc_interrupt_monitor(
    on_interrupt: Callable[[], Coroutine[Any, Any, None]],
) -> tuple[threading.Event, asyncio.Task[None]]:
    """Start a background monitor that triggers a callback on bare ESC.

    This utility watches stdin for a *single* ESC key press (not part of an escape
    sequence like arrow keys). When detected, it schedules the provided
    ``on_interrupt`` coroutine on the current event loop.

    Returns a tuple of ``(stop_event, esc_task)``:
    - ``stop_event`` can be set to request the monitor to stop.
    - ``esc_task`` is the asyncio task running the monitor thread; callers should
      ``await`` it during shutdown to restore TTY state safely.

    If stdin is not a TTY or the platform does not support ``termios`` semantics,
    a no-op task is returned so callers can use the same shutdown code path.
    """

    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    # Fallback for non-interactive or non-POSIX environments.
    if not sys.stdin.isatty() or os.name != "posix":

        async def _noop() -> None:
            return None

        return stop_event, asyncio.create_task(_noop())

    def _esc_monitor(stop: threading.Event) -> None:
        try:
            fd = sys.stdin.fileno()
            old = termios.tcgetattr(fd)
        except OSError as exc:  # pragma: no cover - environment dependent
            log((f"esc monitor init error: {exc}", "r red"))
            return

        try:
            tty.setcbreak(fd)
            while not stop.is_set():
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if not rlist:
                    continue
                try:
                    ch = os.read(fd, 1).decode(errors="ignore")
                except OSError:
                    continue
                if ch != "\x1b":
                    continue

                # Peek following characters to distinguish bare ESC from sequences.
                seq = ""
                r2, _, _ = select.select([sys.stdin], [], [], 0.005)
                while r2:
                    try:
                        seq += os.read(fd, 1).decode(errors="ignore")
                    except OSError:
                        break
                    r2, _, _ = select.select([sys.stdin], [], [], 0.0)

                if seq == "":
                    # Best-effort only; failures here should not crash the UI.
                    with contextlib.suppress(Exception):
                        asyncio.run_coroutine_threadsafe(on_interrupt(), loop)
                    stop.set()
        except Exception as exc:  # pragma: no cover - environment dependent
            log((f"esc monitor error: {exc}", "r red"))
        finally:
            with contextlib.suppress(Exception):
                termios.tcsetattr(fd, termios.TCSADRAIN, old)

    esc_task: asyncio.Task[None] = asyncio.create_task(asyncio.to_thread(_esc_monitor, stop_event))
    return stop_event, esc_task


def install_sigint_interrupt(
    on_interrupt: Callable[[], None],
) -> Callable[[], None]:
    """Install a SIGINT handler that triggers task interrupt and keeps app running.

    Used while waiting for an in-flight task so a single Ctrl+C cancels the
    running task and returns control to the input prompt.
    """

    original_handler = signal.getsignal(signal.SIGINT)

    def _handler(signum: int, frame: FrameType | None) -> None:
        with contextlib.suppress(Exception):
            on_interrupt()

    try:
        signal.signal(signal.SIGINT, _handler)
    except (OSError, ValueError):  # pragma: no cover - platform dependent
        return lambda: None

    def restore() -> None:
        with contextlib.suppress(Exception):
            signal.signal(signal.SIGINT, original_handler)

    return restore
