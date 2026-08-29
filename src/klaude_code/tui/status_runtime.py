"""Wall-clock timing for TUI status display.

Uses time.time() rather than a monotonic clock on purpose: on macOS
perf_counter/monotonic are mach_absolute_time, which pauses while the
machine is asleep, so a task left running through a suspend would display
only its awake time. Wall clock keeps advancing across sleep.
"""

from __future__ import annotations

import time

from klaude_code.tui.components.common import format_elapsed_compact

_process_start: float | None = None
_task_start: float | None = None


def elapsed_since_process_start() -> float:
    """Return seconds elapsed since first use in this process."""

    global _process_start
    now = time.time()
    if _process_start is None:
        _process_start = now
    return now - _process_start


def set_task_start(start: float | None = None) -> None:
    """Set the current task start time (epoch seconds)."""

    global _task_start
    _task_start = time.time() if start is None else start


def clear_task_start() -> None:
    """Clear the current task start time."""

    global _task_start
    _task_start = None


def current_elapsed_text(*, min_time_width: int = 0) -> str | None:
    """Return the current task elapsed time text (e.g. "11s", "1m02s")."""

    if _task_start is None:
        return None

    elapsed = max(0.0, time.time() - _task_start)
    time_text = format_elapsed_compact(elapsed)
    if min_time_width > 0:
        time_text = time_text.rjust(min_time_width)
    return time_text
