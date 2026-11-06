"""Debug-only timing and event-loop stack diagnostics."""

import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from time import monotonic

from klaude_code.log import DebugType, is_debug_enabled, log_debug
from klaude_code.protocol import events


def log_event_stage(stage: str, envelope: events.EventEnvelope) -> None:
    if is_debug_enabled() and isinstance(
        envelope.event, events.UserMessageEvent | events.TaskStartEvent | events.SessionStatusEvent
    ):
        log_debug(
            f"[tui-diagnostic] {stage} session={envelope.session_id} seq={envelope.event_seq}"
            f" event={type(envelope.event).__name__}",
            debug_type=DebugType.EXECUTION,
        )


@contextmanager
def diagnostic_phase(
    stage: str,
    session_id: str,
    *,
    envelope: events.EventEnvelope | None = None,
    slow_only: bool = False,
) -> Iterator[None]:
    if not is_debug_enabled() or (
        envelope is not None
        and not slow_only
        and not isinstance(envelope.event, events.UserMessageEvent | events.TaskStartEvent | events.SessionStatusEvent)
    ):
        yield
        return
    identity = f"session={session_id}"
    if envelope is not None:
        identity += f" seq={envelope.event_seq} event={type(envelope.event).__name__}"
    started = monotonic()
    if not slow_only:
        log_debug(f"[tui-diagnostic] {stage}.begin {identity}", debug_type=DebugType.EXECUTION)
    try:
        yield
    finally:
        elapsed = monotonic() - started
        if not slow_only or elapsed >= 0.1:
            log_debug(
                f"[tui-diagnostic] {stage}.end {identity} elapsed_ms={elapsed * 1000:.1f}",
                debug_type=DebugType.EXECUTION,
            )


class LoopStallSampler:
    """Capture only the loop thread, once per missed heartbeat."""

    def __init__(self, *, interval: float, threshold: float) -> None:
        self._interval = interval
        self._threshold = threshold
        self._loop_thread_id = threading.get_ident()
        self._heartbeat = monotonic()
        self._closed = threading.Event()
        self._thread = threading.Thread(target=self._run, name="tui-stall-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def beat(self) -> None:
        self._heartbeat = monotonic()

    def close(self) -> None:
        self._closed.set()
        # Do not hold shutdown hostage to a blocked log handler.
        self._thread.join(timeout=0.1)

    def _run(self) -> None:
        reported: float | None = None
        while not self._closed.wait(self._interval):
            heartbeat = self._heartbeat
            gap = monotonic() - heartbeat - self._interval
            if gap <= self._threshold or heartbeat == reported or not is_debug_enabled():
                continue
            reported = heartbeat
            frame = sys._current_frames().get(self._loop_thread_id)
            stack: list[str] = []
            try:
                while frame is not None:
                    # Never read locals or source lines (including via traceback formatting).
                    stack.append(f"  {frame.f_code.co_filename}:{frame.f_lineno} in {frame.f_code.co_name}")
                    frame = frame.f_back
            finally:
                del frame
            if not self._closed.is_set():
                log_debug(
                    f"[tui-diagnostic] loop.stalled elapsed_ms={gap * 1000:.1f}\n" + "\n".join(reversed(stack)),
                    debug_type=DebugType.EXECUTION,
                )
