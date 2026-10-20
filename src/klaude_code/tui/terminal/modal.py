"""Cooperative shutdown for terminal modals running in a worker thread."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from threading import Event

from prompt_toolkit.application import Application


def run_modal[T](app: Application[T], closed: Event | None = None) -> T | None:
    if closed is None:
        return app.run()
    if closed.is_set():
        return None

    async def watch() -> None:
        while not closed.is_set():
            await asyncio.sleep(0.05)
        if not app.is_done:
            app.exit()

    def start_watch() -> None:
        app.create_background_task(watch())

    return app.run(pre_run=start_watch)


async def collect_modal[T](collect: Callable[[], T], closed: Event) -> T:
    worker = asyncio.create_task(asyncio.to_thread(collect))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        closed.set()
        # Cancelling to_thread alone leaves its stdin reader alive. Wait for
        # prompt-toolkit to erase the modal and release stdin before resuming.
        await worker
        raise
