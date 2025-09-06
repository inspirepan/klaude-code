import asyncio

import typer

from codex_mini import ui
from codex_mini.config import load_config
from codex_mini.config.list_model import display_models_and_providers
from codex_mini.core.executor import Executor
from codex_mini.llm import LLMClientABC, create_llm_client
from codex_mini.protocol.events import EndEvent, Event
from codex_mini.session import Session
from codex_mini.trace import log, log_debug


def _select_model_from_config(preferred: str | None = None) -> str | None:
    """Interactive single-choice model selector.

    Preferred flow uses questionary TUI when a TTY is available; otherwise
    falls back to numeric input.
    """
    config = load_config()
    models = config.model_list

    if not models:
        raise ValueError("No models configured. Please update your config.yaml")

    names: list[str] = [m.model_name for m in models]
    default_name: str | None = (
        preferred if preferred in names else (config.main_model if config.main_model in names else None)
    )

    try:
        import questionary

        choices: list[questionary.Choice] = []

        max_model_name_length = max(len(m.model_name) for m in models)
        print(max_model_name_length)
        for m in models:
            star = "★ " if m.model_name == config.main_model else "  "
            label = [
                ("class:text", f"{star}{m.model_name:<{max_model_name_length}}   → "),
                ("class:b", m.model_params.model or "N/A"),
                ("class:d", f" {m.provider}"),
            ]
            choices.append(questionary.Choice(title=label, value=m.model_name))

        result = questionary.select(
            message="Select a model:",
            choices=choices,
            default=default_name,
            pointer="→",
            instruction="↑↓ to move • Enter to select",
            style=questionary.Style(
                [
                    ("text", ""),
                    ("b", "bold"),
                    ("d", "dim"),
                ]
            ),
        ).ask()
        if isinstance(result, str) and result in names:
            return result
    except Exception as e:
        log_debug(f"Failed to use questionary, falling back to default model, {e}")
        pass


async def run_interactive(model: str | None = None, debug: bool = False, continue_session: bool = False):
    """Run the interactive REPL using the new executor architecture."""
    config = load_config()
    llm_config = config.get_model_config(model) if model else config.get_main_model_config()

    if debug:
        log_debug("▷▷▷ llm [Model Config]", llm_config.model_dump_json(exclude_none=True), style="yellow")

    llm_client: LLMClientABC = create_llm_client(llm_config)
    if debug:
        llm_client.enable_debug_mode()

    # Create event queue for communication between executor and UI
    event_queue: asyncio.Queue[Event] = asyncio.Queue()

    # Create executor with the LLM client
    executor = Executor(event_queue, llm_client, llm_config, debug_mode=debug)

    # Start executor in background
    executor_task = asyncio.create_task(executor.start())

    # Set up UI components
    display: ui.DisplayABC = ui.REPLDisplay() if not debug else ui.DebugEventDisplay()
    input_provider: ui.InputProviderABC = ui.PromptToolkitInput()

    # Start UI display task
    display_task = asyncio.create_task(display.consume_event_loop(event_queue))

    # Determine session to continue if requested
    session_id: str | None = None
    if continue_session:
        session_id = Session.most_recent_session_id()

    try:
        # Init Agent
        init_id = await executor.submit({"type": "init_agent", "session_id": session_id})
        await executor.wait_for_completion(init_id)
        await event_queue.join()
        # Input
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
                    "session_id": session_id,
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
    select_model: bool = typer.Option(
        False,
        "--select-model",
        "-s",
        help="Interactively choose a model at startup",
    ),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
    continue_: bool = typer.Option(False, "--continue", "-c", help="Continue from latest session"),
):
    """Root command callback. Runs interactive mode when no subcommand provided."""
    # Only run interactive mode when no subcommand is invoked
    if ctx.invoked_subcommand is None:
        chosen_model = model
        if select_model:
            # Prefer the explicitly provided model as default; otherwise main model
            default_name = model or load_config().main_model
            chosen_model = _select_model_from_config(preferred=default_name)
            if chosen_model is None:
                return
        asyncio.run(run_interactive(model=chosen_model, debug=debug, continue_session=continue_))
