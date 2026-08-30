"""Detect an OS suspend that happened while a step's LLM request was in flight.

``time.time()`` keeps advancing while the machine is asleep; ``time.monotonic()``
does not (mach_absolute_time on macOS, CLOCK_MONOTONIC on Linux). The gap that
opens between the two over the life of a request is the time spent suspended,
so a stream that died across a sleep can be reported as such instead of as a
bare transport error.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from klaude_code.const import SUSPEND_DETECTION_THRESHOLD_S


class SuspendDetector:
    """Measures how long the machine was suspended since construction."""

    def __init__(
        self,
        *,
        wall_clock: Callable[[], float] = time.time,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._wall_clock = wall_clock
        self._monotonic_clock = monotonic_clock
        self._wall_start = wall_clock()
        self._monotonic_start = monotonic_clock()

    def suspended_seconds(self) -> float:
        """Seconds the machine spent suspended since construction (0 when awake throughout)."""

        wall_elapsed = self._wall_clock() - self._wall_start
        monotonic_elapsed = self._monotonic_clock() - self._monotonic_start
        return max(0.0, wall_elapsed - monotonic_elapsed)

    def suspended(self) -> bool:
        """True when the suspend gap is large enough to count as the machine sleeping."""

        return self.suspended_seconds() >= SUSPEND_DETECTION_THRESHOLD_S


def suspend_notice(suspended_seconds: float, *, partial_output: bool) -> str:
    """User-facing explanation for a stream that died across an OS suspend.

    ``partial_output`` says whether any of the response reached the screen, so
    the notice can point at it instead of at nothing.
    """

    duration = _format_duration(suspended_seconds)
    if partial_output:
        return f"Your computer went to sleep mid-response ({duration} suspended). The response above may be incomplete."
    return f"Your computer went to sleep mid-request ({duration} suspended) before any response arrived."


def _format_duration(seconds: float) -> str:
    total = max(0, int(seconds))
    if total < 60:
        return f"{total}s"
    minutes, _ = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"
