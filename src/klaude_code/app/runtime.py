import asyncio
import contextlib
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

import typer

from klaude_code.app.ports import DisplayABC, InteractionHandlerABC
from klaude_code.config import Config, load_config
from klaude_code.core.agent.agent import Agent
from klaude_code.core.agent.runtime_llm import build_llm_clients
from klaude_code.core.agent_profile import (
    DefaultModelProfileProvider,
    VanillaModelProfileProvider,
)
from klaude_code.core.control.event_bus import EventBus, EventSubscription
from klaude_code.core.control.event_relay import EventRelayPublisher, event_relay_socket_path
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.core.control.session_meta_relay import SessionMetaRelayPublisher, session_meta_relay_socket_path
from klaude_code.log import log, set_debug_logging
from klaude_code.protocol import events, op, user_interaction
from klaude_code.session.session import Session, close_default_store
from klaude_code.session.store import register_session_meta_observer

SESSION_IDLE_TTL_SECONDS = 30 * 60
SESSION_IDLE_RECLAIM_INTERVAL_SECONDS = 60
SESSION_OWNER_HEARTBEAT_INTERVAL_SECONDS = 5


@dataclass
class AppInitConfig:
    """Configuration for initializing the application runtime."""

    model: str | None
    debug: bool
    vanilla: bool
    runtime_kind: Literal["tui", "web"] = "tui"
    enable_event_relay_client: bool = True


@dataclass
class AppComponents:
    """Initialized runtime components."""

    config: Config
    runtime: RuntimeFacade
    event_bus: EventBus
    event_relay_publisher: EventRelayPublisher | None
    session_meta_relay_publisher: SessionMetaRelayPublisher | None
    unregister_session_meta_relay_observer: Callable[[], None] | None
    event_bus_subscription: EventSubscription
    display: DisplayABC
    display_task: asyncio.Task[None]
    interaction_task: asyncio.Task[None] | None
    idle_reclaim_task: asyncio.Task[None]
    owner_heartbeat_task: asyncio.Task[None]

    async def wait_for_display_idle(self) -> None:
        """Wait until EventBus subscription has consumed pending events."""
        await self.event_bus_subscription.wait_for_drain()


async def _consume_display_from_subscription(
    subscription: EventSubscription,
    display: DisplayABC,
) -> None:
    await display.start()
    async for envelope in subscription:
        try:
            if isinstance(envelope.event, events.EndEvent):
                await display.stop()
                return
            await display.consume_envelope(envelope)
        except Exception as e:
            import traceback

            log(f"Error in display event stream, {e.__class__.__name__}, {e}")
            log(traceback.format_exc())


async def _reclaim_idle_sessions_loop(runtime: RuntimeFacade) -> None:
    while True:
        await asyncio.sleep(SESSION_IDLE_RECLAIM_INTERVAL_SECONDS)
        await runtime.reclaim_idle_sessions(idle_for_seconds=SESSION_IDLE_TTL_SECONDS)


async def _heartbeat_session_owners_loop(runtime: RuntimeFacade) -> None:
    while True:
        await asyncio.sleep(SESSION_OWNER_HEARTBEAT_INTERVAL_SECONDS)
        await runtime.heartbeat_session_owners()


async def _consume_interactions_from_subscription(
    subscription: EventSubscription,
    runtime: RuntimeFacade,
    handler: InteractionHandlerABC,
) -> None:
    async for envelope in subscription:
        event = envelope.event
        if isinstance(event, events.EndEvent):
            return
        if not isinstance(event, events.UserInteractionRequestEvent):
            continue

        try:
            response = await handler.collect_response(event)
        except asyncio.CancelledError:
            raise
        except Exception:
            response = user_interaction.UserInteractionResponse(status="cancelled", payload=None)

        await runtime.submit_and_wait(
            op.UserInteractionRespondOperation(
                session_id=event.session_id,
                request_id=event.request_id,
                response=response,
            )
        )


async def initialize_app_components(
    *,
    init_config: AppInitConfig,
    display: DisplayABC,
    interaction_handler: InteractionHandlerABC | None = None,
    on_model_change: Callable[[str], None] | None = None,
) -> AppComponents:
    """Initialize LLM clients, runtime, and display task."""
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

    event_relay_publisher: EventRelayPublisher | None = None
    session_meta_relay_publisher: SessionMetaRelayPublisher | None = None
    unregister_session_meta_relay_observer: Callable[[], None] | None = None
    if init_config.enable_event_relay_client:
        event_relay_publisher = EventRelayPublisher(socket_path=event_relay_socket_path())
        session_meta_relay_publisher = SessionMetaRelayPublisher(socket_path=session_meta_relay_socket_path())
        unregister_session_meta_relay_observer = register_session_meta_observer(
            lambda session_id, meta: session_meta_relay_publisher.publish_upsert(session_id, meta)
        )

    event_bus = EventBus(publish_hook=event_relay_publisher.publish if event_relay_publisher is not None else None)
    event_bus_subscription = event_bus.subscribe(None)
    interaction_subscription = event_bus.subscribe(None) if interaction_handler is not None else None

    runtime = RuntimeFacade(
        event_bus,
        llm_clients,
        model_profile_provider=model_profile_provider,
        on_model_change=on_model_change,
        runtime_kind=init_config.runtime_kind,
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

    idle_reclaim_task = asyncio.create_task(_reclaim_idle_sessions_loop(runtime))
    _drain_background_task_exception(idle_reclaim_task, label="idle-reclaim")

    owner_heartbeat_task = asyncio.create_task(_heartbeat_session_owners_loop(runtime))
    _drain_background_task_exception(owner_heartbeat_task, label="owner-heartbeat")

    display_task = asyncio.create_task(_consume_display_from_subscription(event_bus_subscription, display))
    _drain_background_task_exception(display_task, label="display")

    interaction_task: asyncio.Task[None] | None = None
    if interaction_subscription is not None and interaction_handler is not None:
        interaction_task = asyncio.create_task(
            _consume_interactions_from_subscription(interaction_subscription, runtime, interaction_handler)
        )
        _drain_background_task_exception(interaction_task, label="interaction")

    return AppComponents(
        config=config,
        runtime=runtime,
        event_bus=event_bus,
        event_relay_publisher=event_relay_publisher,
        session_meta_relay_publisher=session_meta_relay_publisher,
        unregister_session_meta_relay_observer=unregister_session_meta_relay_observer,
        event_bus_subscription=event_bus_subscription,
        display=display,
        display_task=display_task,
        interaction_task=interaction_task,
        idle_reclaim_task=idle_reclaim_task,
        owner_heartbeat_task=owner_heartbeat_task,
    )


async def initialize_session(
    runtime: RuntimeFacade,
    wait_for_display_idle: Callable[[], Awaitable[None]],
    session_id: str | None = None,
    *,
    holder_key: str | None = None,
) -> str | None:
    """Initialize a session and return the active session id."""
    resolved_session_id = session_id or uuid4().hex
    await runtime.submit_and_wait(op.InitAgentOperation(session_id=resolved_session_id, work_dir=Path.cwd()))
    await wait_for_display_idle()

    active_session_id = runtime.current_session_id() or resolved_session_id

    if holder_key is not None:
        await runtime.try_acquire_holder(active_session_id, holder_key)

    return active_session_id


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
        if components.unregister_session_meta_relay_observer is not None:
            components.unregister_session_meta_relay_observer()

        components.idle_reclaim_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await components.idle_reclaim_task

        components.owner_heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await components.owner_heartbeat_task

        await components.runtime.stop()
        with contextlib.suppress(Exception):
            await close_default_store()

        with contextlib.suppress(Exception):
            await components.wait_for_display_idle()

        with contextlib.suppress(Exception):
            await components.event_bus.publish(events.EndEvent())

        if components.event_relay_publisher is not None:
            with contextlib.suppress(Exception):
                await components.event_relay_publisher.aclose()

        if components.session_meta_relay_publisher is not None:
            with contextlib.suppress(Exception):
                components.session_meta_relay_publisher.close()

        if components.interaction_task is not None:
            with contextlib.suppress(Exception):
                await components.interaction_task
        await components.display_task
    finally:
        # Ensure the terminal cursor is visible even if Rich's spinner did not stop cleanly.
        with contextlib.suppress(Exception):
            stream = getattr(sys, "__stdout__", None) or sys.stdout
            stream.write("\033[?25h")
            stream.flush()


async def handle_keyboard_interrupt(runtime: RuntimeFacade) -> None:
    """Handle Ctrl+C by logging and interrupting only if a task is running."""
    log("Bye!")
    session_id = runtime.current_session_id()
    if session_id and Session.exists(session_id, work_dir=Path.cwd()):
        short_id = Session.shortest_unique_prefix(session_id, work_dir=Path.cwd())
        log(("Resume with:", "dim"), (f"klaude -r {short_id}", "green"))
    if not runtime.has_running_tasks():
        return
    if session_id is None:
        return
    with contextlib.suppress(Exception):
        await runtime.submit(op.InterruptOperation(session_id=session_id))
