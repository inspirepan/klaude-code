import contextlib
import signal
from collections.abc import Callable
from types import FrameType


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
