"""Translate terminal/process termination into awaited Runtime cleanup."""

import asyncio
import contextlib
import signal
from collections.abc import Iterator


@contextlib.contextmanager
def cancel_on_termination() -> Iterator[None]:
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    previous = {}
    if task is not None:
        for signum in (signal.SIGTERM, signal.SIGHUP):
            handler = signal.getsignal(signum)
            try:
                loop.add_signal_handler(signum, task.cancel)
            except (NotImplementedError, RuntimeError, ValueError):
                continue
            previous[signum] = handler
    try:
        yield
    finally:
        for signum, handler in previous.items():
            loop.remove_signal_handler(signum)
            signal.signal(signum, handler)
