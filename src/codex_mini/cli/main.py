import asyncio
from collections.abc import AsyncGenerator

import typer

from codex_mini.config import load_config
from codex_mini.core import Agent
from codex_mini.core.tool import BASH_TOOL_NAME, get_tool_schemas
from codex_mini.llm import LLMClientABC, create_llm_client
from codex_mini.protocol.events import EndEvent, Event
from codex_mini.trace.log import log
from codex_mini.ui import PromptToolkitInput, REPLDisplay


async def forward_event(gen: AsyncGenerator[Event, None], q: asyncio.Queue[Event]):
    try:
        async for event in gen:
            await q.put(event)
    except Exception as e:
        raise e


async def run_interactive(model: str | None = None):
    config = load_config()
    model_config = (
        config.get_model_config(model) if model else config.get_main_model_config()
    )
    llm_client: LLMClientABC = create_llm_client(model_config)
    agent: Agent = Agent(
        llm_client=llm_client, tools=get_tool_schemas([BASH_TOOL_NAME])
    )

    q: asyncio.Queue[Event] = asyncio.Queue()

    display = REPLDisplay()
    input_provider = PromptToolkitInput()

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


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
    ),
):
    """Root command callback. Runs interactive mode when no subcommand provided."""
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        asyncio.run(run_interactive(model=model))
