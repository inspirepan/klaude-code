import asyncio
import os
from collections.abc import AsyncGenerator
from typing import Annotated

import typer

from src.agent import Agent
from src.config import load_config
from src.llm import LLMClient, create_llm_client
from src.protocal import EndEvent, Event
from src.trace.log import log
from src.ui import StdoutDisplay
from src.ui.input_ptk import PromptToolkitInput


async def forward_event(gen: AsyncGenerator[Event, None], q: asyncio.Queue[Event]):
    try:
        async for event in gen:
            await q.put(event)
    except Exception as e:
        raise e


async def run_interactive(ui: str = "stdout"):
    config = load_config()
    llm_client: LLMClient = create_llm_client(config.llm_config)
    agent: Agent = Agent(llm_client=llm_client)

    q: asyncio.Queue[Event] = asyncio.Queue()

    # Choose display and input provider
    if ui == "textual":
        # Lazy import to avoid requiring textual when using stdout UI
        from src.ui.tui import TextualDisplay, TextualInput  # type: ignore

        display = TextualDisplay()
        input_provider = TextualInput(display)
    else:
        display = StdoutDisplay()
        input_provider = PromptToolkitInput(prompt="> ")

    display_task = asyncio.create_task(display.consume_event_loop(q))

    try:
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            if user_input.strip().lower() in {"exit", ":q", "quit"}:
                break
            await forward_event(agent.run_task(user_input), q)
            await q.join()  # ensure events drained before next input
    except KeyboardInterrupt:
        log("Bye!")
    finally:
        await q.put(EndEvent())
        await display_task


app = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@app.command()
def main(
    ui: Annotated[str, typer.Option(help="UI backend: stdout|textual")] = "stdout",
):
    ui_choice = os.getenv("CODEX_UI", ui)
    asyncio.run(run_interactive(ui_choice))
