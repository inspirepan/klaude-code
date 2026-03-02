import asyncio
import contextlib
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import typer

from klaude_code import ui
from klaude_code.config import Config, load_config
from klaude_code.core.agent import Agent
from klaude_code.core.agent_profile import (
    DefaultModelProfileProvider,
    VanillaModelProfileProvider,
)
from klaude_code.core.event_bus import EventBus, EventSubscription
from klaude_code.core.executor import Executor
from klaude_code.core.manager import build_llm_clients
from klaude_code.log import log, set_debug_logging
from klaude_code.protocol import events, op
from klaude_code.session.session import Session, close_default_store

SESSION_IDLE_TTL_SECONDS = 30 * 60
SESSION_IDLE_RECLAIM_INTERVAL_SECONDS = 60


@dataclass
class AppInitConfig:
    """Configuration for initializing the application runtime."""

    model: str | None
    debug: bool
    vanilla: bool


@dataclass
class AppComponents:
    """Initialized runtime components."""

    config: Config
    executor: Executor
    event_bus: EventBus
    event_bus_subscription: EventSubscription
    display: ui.DisplayABC
    display_task: asyncio.Task[None]
    idle_reclaim_task: asyncio.Task[None]

    async def wait_for_display_idle(self) -> None:
        """Wait until EventBus subscription has consumed pending events."""
        await self.event_bus_subscription.wait_for_drain()


async def _consume_display_from_subscription(
    subscription: EventSubscription,
    display: ui.DisplayABC,
) -> None:
    await display.start()
    async for event in subscription.iter_events():
        try:
            if isinstance(event, events.EndEvent):
                await display.stop()
                return
            await display.consume_event(event)
        except Exception as e:
            import traceback

            log(
                f"Error in display event stream, {e.__class__.__name__}, {e}",
                style="red",
            )
            log(traceback.format_exc(), style="red")


async def _reclaim_idle_sessions_loop(executor: Executor) -> None:
    while True:
        await asyncio.sleep(SESSION_IDLE_RECLAIM_INTERVAL_SECONDS)
        await executor.reclaim_idle_sessions(idle_for_seconds=SESSION_IDLE_TTL_SECONDS)


async def initialize_app_components(
    *,
    init_config: AppInitConfig,
    display: ui.DisplayABC,
    on_model_change: Callable[[str], None] | None = None,
) -> AppComponents:
    """Initialize LLM clients, executor, and display task."""
    set_debug_logging(init_config.debug)

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
                    f"Error: model '{init_config.model}' is not defined in the config, {exc}",
                    "red",
                )
            )
            log(("Hint: run `klaude list` to view available models", "yellow"))
        else:
            log((f"Error: failed to load the default model configuration: {exc}", "red"))
            log(("Hint: run `klaude conf` to edit the config file", "yellow"))
        raise typer.Exit(2) from None

    if init_config.vanilla:
        model_profile_provider = VanillaModelProfileProvider()
    else:
        model_profile_provider = DefaultModelProfileProvider(config=config)

    event_bus = EventBus()
    event_bus_subscription = event_bus.subscribe(None)

    executor = Executor(
        event_bus,
        llm_clients,
        model_profile_provider=model_profile_provider,
        on_model_change=on_model_change,
    )

    if on_model_change is not None:
        on_model_change(llm_clients.main_model_alias)

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

    idle_reclaim_task = asyncio.create_task(_reclaim_idle_sessions_loop(executor))
    _drain_background_task_exception(idle_reclaim_task, label="idle-reclaim")

    display_task = asyncio.create_task(_consume_display_from_subscription(event_bus_subscription, display))
    _drain_background_task_exception(display_task, label="display")

    return AppComponents(
        config=config,
        executor=executor,
        event_bus=event_bus,
        event_bus_subscription=event_bus_subscription,
        display=display,
        display_task=display_task,
        idle_reclaim_task=idle_reclaim_task,
    )


async def initialize_session(
    executor: Executor,
    wait_for_display_idle: Callable[[], Awaitable[None]],
    session_id: str | None = None,
) -> str | None:
    """Initialize a session and return the active session id."""
    await executor.submit_and_wait(op.InitAgentOperation(session_id=session_id))
    await wait_for_display_idle()

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
        components.idle_reclaim_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await components.idle_reclaim_task

        await components.executor.stop()
        with contextlib.suppress(Exception):
            await close_default_store()

        with contextlib.suppress(Exception):
            await components.wait_for_display_idle()

        with contextlib.suppress(Exception):
            await components.event_bus.publish(events.EndEvent())
        await components.display_task
    finally:
        # Ensure the terminal cursor is visible even if Rich's spinner did not stop cleanly.
        with contextlib.suppress(Exception):
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()


async def handle_keyboard_interrupt(executor: Executor) -> None:
    """Handle Ctrl+C by logging and interrupting only if a task is running."""
    log("Bye!")
    session_id = executor.context.current_session_id()
    if session_id and Session.exists(session_id):
        short_id = Session.shortest_unique_prefix(session_id)
        log(("Resume with:", "dim"), (f"klaude -r {short_id}", "green"))
    if not executor.has_running_tasks():
        return
    with contextlib.suppress(Exception):
        await executor.submit(op.InterruptOperation(target_session_id=None))
