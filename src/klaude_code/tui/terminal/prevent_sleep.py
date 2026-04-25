from __future__ import annotations

import atexit
import contextlib
import os
import signal
import subprocess
import sys
import threading
from types import FrameType

from klaude_code.log import DebugType, log_debug

CAFFEINATE_TIMEOUT_SECONDS = 300
RESTART_INTERVAL_SECONDS = 4 * 60

_lock = threading.Lock()
_caffeinate_process: subprocess.Popen[bytes] | None = None
_restart_timer: threading.Timer | None = None
_ref_count = 0
_cleanup_registered = False
_signal_handlers_registered = False


def start_prevent_sleep() -> None:
    """Prevent macOS idle sleep while TUI work is active."""

    global _ref_count
    with _lock:
        _ref_count += 1
        if _ref_count == 1:
            _spawn_caffeinate_locked()
            _start_restart_timer_locked()


def stop_prevent_sleep() -> None:
    """Release one active idle-sleep prevention request."""

    global _ref_count
    with _lock:
        if _ref_count > 0:
            _ref_count -= 1
        if _ref_count == 0:
            _stop_restart_timer_locked()
            _kill_caffeinate_locked()


def force_stop_prevent_sleep() -> None:
    """Release all idle-sleep prevention state immediately."""

    global _ref_count
    with _lock:
        _ref_count = 0
        _stop_restart_timer_locked()
        _kill_caffeinate_locked()


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _start_restart_timer_locked() -> None:
    global _restart_timer
    if not _is_macos() or _restart_timer is not None:
        return
    _restart_timer = threading.Timer(RESTART_INTERVAL_SECONDS, _restart_caffeinate)
    _restart_timer.daemon = True
    _restart_timer.start()


def _stop_restart_timer_locked() -> None:
    global _restart_timer
    if _restart_timer is not None:
        _restart_timer.cancel()
        _restart_timer = None


def _restart_caffeinate() -> None:
    global _restart_timer
    with _lock:
        _restart_timer = None
        if _ref_count <= 0:
            return
        log_debug("Restarting caffeinate to maintain sleep prevention", debug_type=DebugType.TERMINAL)
        _kill_caffeinate_locked()
        _spawn_caffeinate_locked()
        _start_restart_timer_locked()


def _spawn_caffeinate_locked() -> None:
    global _caffeinate_process, _cleanup_registered
    if not _is_macos() or _caffeinate_process is not None:
        return

    if not _cleanup_registered:
        _cleanup_registered = True
        atexit.register(force_stop_prevent_sleep)
        _register_exit_signal_handlers_locked()

    try:
        _caffeinate_process = subprocess.Popen(
            ["caffeinate", "-i", "-t", str(CAFFEINATE_TIMEOUT_SECONDS)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        log_debug("Started caffeinate to prevent sleep", debug_type=DebugType.TERMINAL)
    except (OSError, subprocess.SubprocessError) as exc:
        _caffeinate_process = None
        log_debug(f"caffeinate spawn error: {exc}", debug_type=DebugType.TERMINAL)


def _kill_caffeinate_locked() -> None:
    global _caffeinate_process
    if _caffeinate_process is None:
        return

    proc = _caffeinate_process
    _caffeinate_process = None
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc.kill()
        proc.wait(timeout=1.0)
        log_debug("Stopped caffeinate, allowing sleep", debug_type=DebugType.TERMINAL)


def _register_exit_signal_handlers_locked() -> None:
    global _signal_handlers_registered
    if _signal_handlers_registered:
        return
    _signal_handlers_registered = True

    for signum in (signal.SIGTERM, getattr(signal, "SIGHUP", None)):
        if signum is None:
            continue
        try:
            original_handler = signal.getsignal(signum)
            if original_handler is not signal.SIG_DFL:
                continue
            signal.signal(signum, _handle_exit_signal)
        except (OSError, ValueError):
            continue


def _handle_exit_signal(signum: int, frame: FrameType | None) -> None:
    del frame
    _kill_caffeinate_for_signal()
    with contextlib.suppress(OSError, ValueError):
        signal.signal(signum, signal.SIG_DFL)
    os.kill(os.getpid(), signum)


def _kill_caffeinate_for_signal() -> None:
    global _caffeinate_process
    proc = _caffeinate_process
    _caffeinate_process = None
    if proc is None:
        return
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        proc.kill()
