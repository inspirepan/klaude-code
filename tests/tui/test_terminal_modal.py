from __future__ import annotations

import asyncio
from threading import Event

import pytest
from prompt_toolkit.application import Application
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from klaude_code.tui.terminal.modal import collect_modal, run_modal


@pytest.mark.parametrize("cancel_task", [False, True])
def test_modal_releases_input_on_remote_close_or_runner_cancel(cancel_task: bool) -> None:
    async def scenario() -> None:
        closed, started, released = Event(), Event(), Event()

        def collect() -> None:
            with create_pipe_input() as pipe:
                app: Application[None] = Application(input=pipe, output=DummyOutput())
                app.before_render += lambda _: started.set()
                try:
                    run_modal(app, closed)
                finally:
                    released.set()

        task = asyncio.create_task(collect_modal(collect, closed))
        assert await asyncio.to_thread(started.wait, 2)
        if cancel_task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 2)
        else:
            closed.set()
            await asyncio.wait_for(task, 2)
        assert released.is_set()

    asyncio.run(scenario())
