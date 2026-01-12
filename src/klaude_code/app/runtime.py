import asyncio
import contextlib
import sys
from collections.abc import Callable
from dataclasses import dataclass

import typer

from klaude_code import ui
from klaude_code.config import Config, load_config
from klaude_code.core.agent import Agent
from klaude_code.core.agent_profile import (
    DefaultModelProfileProvider,
    VanillaModelProfileProvider,
)
from klaude_code.core.executor import Executor
from klaude_code.core.manager import build_llm_clients
from klaude_code.log import DebugType, log, set_debug_logging
from klaude_code.protocol import events, op
from klaude_code.session.session import Session, close_default_store


@dataclass
class AppInitConfig:
    """Configuration for initializing the application runtime."""

    model: str | None
    debug: bool
    vanilla: bool
    debug_filters: set[DebugType] | None = None


@dataclass
class AppComponents:
    """Initialized runtime components."""

    config: Config
    executor: Executor
    executor_task: asyncio.Task[None]
    event_queue: asyncio.Queue[events.Event]
    display: ui.DisplayABC
    display_task: asyncio.Task[None]


async def initialize_app_components(
    *,
    init_config: AppInitConfig,
    display: ui.DisplayABC,
    on_model_change: Callable[[str], None] | None = None,
) -> AppComponents:
    """Initialize LLM clients, executor, and display task."""
    set_debug_logging(init_config.debug, filters=init_config.debug_filters)

    config = load_config()

    try:
        llm_clients = build_llm_clients(
            config,
            model_override=init_config.model,
            skip_sub_agents=init_config.vanilla,
        )
    except ValueError as exc:
        if init_config.model:
            log(
                (
                    f"Error: model '{init_config.model}' is not defined in the config",
                    "red",
                )
            )
            log(("Hint: run `klaude list` to view available models", "yellow"))
        else:
            log((f"Error: failed to load the default model configuration: {exc}", "red"))
        raise typer.Exit(2) from None

    if init_config.vanilla:
        model_profile_provider = VanillaModelProfileProvider()
    else:
        model_profile_provider = DefaultModelProfileProvider(config=config)

    event_queue: asyncio.Queue[events.Event] = asyncio.Queue()

    executor = Executor(
        event_queue,
        llm_clients,
        model_profile_provider=model_profile_provider,
        on_model_change=on_model_change,
    )

    if on_model_change is not None:
        on_model_change(llm_clients.main_model_alias)

    executor_task = asyncio.create_task(executor.start())

    def _drain_background_task_exception(task: asyncio.Task[None], *, label: str) -> None:
        def _on_done(t: asyncio.Task[None]) -> None:
            with contextlib.suppress(asyncio.CancelledError):
                exc = t.exception()
                if exc is None:
                    return
                if isinstance(exc, KeyboardInterrupt):
                    return
                log((f"Background task '{label}' failed: {exc}", "red"))

        task.add_done_callback(_on_done)

    _drain_background_task_exception(executor_task, label="executor")

    display_task = asyncio.create_task(display.consume_event_loop(event_queue))
    _drain_background_task_exception(display_task, label="display")

    return AppComponents(
        config=config,
        executor=executor,
        executor_task=executor_task,
        event_queue=event_queue,
        display=display,
        display_task=display_task,
    )


async def initialize_session(
    executor: Executor,
    event_queue: asyncio.Queue[events.Event],
    session_id: str | None = None,
) -> str | None:
    """Initialize a session and return the active session id."""
    await executor.submit_and_wait(op.InitAgentOperation(session_id=session_id))
    await event_queue.join()

    active_session_id = executor.context.current_session_id()
    return active_session_id or session_id


def backfill_session_model_config(
    agent: Agent | None,
    model_override: str | None,
    default_model: str | None,
    *,
    is_new_session: bool,
) -> None:
    """Backfill model_config_name and model_thinking on newly created sessions."""
    if agent is None or agent.session.model_config_name is not None:
        return

    if model_override is not None:
        agent.session.model_config_name = model_override
    elif is_new_session and default_model is not None:
        agent.session.model_config_name = default_model
    else:
        return

    if agent.session.model_thinking is None and agent.profile:
        agent.session.model_thinking = agent.profile.llm_client.get_llm_config().thinking


async def cleanup_app_components(components: AppComponents) -> None:
    """Clean up all runtime components."""
    try:
        await components.executor.stop()
        components.executor_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await components.executor_task
        with contextlib.suppress(Exception):
            await close_default_store()

        await components.event_queue.put(events.EndEvent())
        await components.display_task
    finally:
        # Ensure the terminal cursor is visible even if Rich's spinner did not stop cleanly.
        with contextlib.suppress(Exception):
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()


async def handle_keyboard_interrupt(executor: Executor) -> None:
    """Handle Ctrl+C by logging and sending a global interrupt."""
    log("Bye!")
    session_id = executor.context.current_session_id()
    if session_id and Session.exists(session_id):
        short_id = Session.shortest_unique_prefix(session_id)
        log(("Resume with:", "dim"), (f"klaude -r {short_id}", "green"))
    with contextlib.suppress(Exception):
        await executor.submit(op.InterruptOperation(target_session_id=None))
