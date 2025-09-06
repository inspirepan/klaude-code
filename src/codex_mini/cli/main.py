import asyncio

import typer

from codex_mini import ui
from codex_mini.config import load_config
from codex_mini.config.list_model import display_models_and_providers
from codex_mini.core.executor import Executor
from codex_mini.llm import LLMClientABC, create_llm_client
from codex_mini.protocol.events import EndEvent, Event
from codex_mini.trace import log, log_debug


async def run_interactive(model: str | None = None, debug: bool = False):
    """Run the interactive REPL using the new executor architecture."""
    config = load_config()
    model_config = config.get_model_config(model) if model else config.get_main_model_config()

    if debug:
        log_debug("▷▷▷ llm [Model Config]", model_config.model_dump_json(exclude_none=True), style="yellow")

    llm_client: LLMClientABC = create_llm_client(model_config)
    if debug:
        llm_client.enable_debug_mode()

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(event_queue, llm_client, debug_mode=debug)

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    # Set up UI components
    display: ui.DisplayABC = ui.REPLDisplay() if not debug else ui.DebugEventDisplay()
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput()

    # Start UI display task
    display_task = asyncio.create_task(display.consume_event_loop(event_queue))

    try:
        await input_provider.start()
        async for user_input in input_provider.iter_inputs():
            # Handle special commands
            if user_input.strip().lower() in {"exit", ":q", "quit"}:
                break
            elif user_input.strip() == "":
                continue
            # Submit user input operation
            submission_id = await executor.submit(
                {
                    "type": "user_input",
                    "content": user_input,
                    "session_id": None,  # Use default session
                }
            )
            # Wait for this specific task to complete before accepting next input
            await executor.wait_for_completion(submission_id)
            # Ensure all UI events drained before next input
            await event_queue.join()

    except KeyboardInterrupt:
        log("Interrupted! Bye!")
        # Send interrupt to stop any running tasks
        try:
            await executor.submit({"type": "interrupt", "target_session_id": None})
        except:  # noqa: E722
            pass  # Executor might already be stopping
    finally:
        # Clean shutdown
        await executor.stop()
        executor_task.cancel()

        # Signal UI to stop
        await event_queue.put(EndEvent())
        await display_task


app = typer.Typer(
    add_completion=False,
    pretty_exceptions_enable=False,
    no_args_is_help=False,
)


@app.command("list")
def list_models():
    """List all models and providers configuration"""
    config = load_config()
    display_models_and_providers(config)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    model: str | None = typer.Option(
        None,
        "--model",
        "-m",
        help="Override model config name (uses main model by default)",
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
):
    """Root command callback. Runs interactive mode when no subcommand provided."""
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        asyncio.run(run_interactive(model=model, debug=debug))
