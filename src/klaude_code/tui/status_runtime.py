from __future__ import annotations

import time

from klaude_code.tui.components.common import format_elapsed_compact

_process_start: float | None = None
_task_start: float | None = None

def elapsed_since_process_start() -> float:
    """Return seconds elapsed since first use in this process."""

    global _process_start
    now = time.perf_counter()
    if _process_start is None:
        _process_start = now
    return now - _process_start

def set_task_start(start: float | None = None) -> None:
    """Set the current task start time (perf_counter seconds)."""

    global _task_start
    _task_start = time.perf_counter() if start is None else start

def clear_task_start() -> None:
    """Clear the current task start time."""

    global _task_start
    _task_start = None

def current_elapsed_text(*, min_time_width: int = 0) -> str | None:
    """Return the current task elapsed time text (e.g. "11s", "1m02s")."""

    if _task_start is None:
        return None

    elapsed = max(0.0, time.perf_counter() - _task_start)
    time_text = format_elapsed_compact(elapsed)
    if min_time_width > 0:
        time_text = time_text.rjust(min_time_width)
    return time_text
