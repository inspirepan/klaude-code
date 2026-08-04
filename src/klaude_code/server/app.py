from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EnvelopeBus, EventBus
from klaude_code.log import DebugType, log_debug
from klaude_code.server.headless import HeadlessRuntime
from klaude_code.server.interaction import ServerInteractionHandler
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.routes import headless_router, server_router, sessions_router, ws_router
from klaude_code.server.session_live import SessionLiveState
from klaude_code.server.session_tape import SessionEventTapes
from klaude_code.server.state import ServerAppState, get_server_state_from_app
from klaude_code.session.store import register_session_meta_observer
from klaude_code.update import get_code_fingerprint


def create_app(
    *,
    runtime: RuntimeFacade | None = None,
    event_bus: EventBus | None = None,
    event_stream: EnvelopeBus | None = None,
    interaction_handler: ServerInteractionHandler | None = None,
    work_dir: Path,
    home_dir: Path | None = None,
    lifecycle: ServerLifecycle | None = None,
    state_initializer: Callable[[], Awaitable[ServerAppState]] | None = None,
    state_shutdown: Callable[[ServerAppState], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        unregister_meta_observer: Callable[[], None] | None = None
        if state_initializer is not None:
            app.state.server_state = await state_initializer()
        state = get_server_state_from_app(app)
        if not state.code_fingerprint:
            state = replace(state, code_fingerprint=get_code_fingerprint())
            app.state.server_state = state
        if state.session_live is None:
            state = replace(state, session_live=SessionLiveState(home_dir=state.home_dir, runtime=state.runtime))
            app.state.server_state = state
        if state.tapes is None:
            state = replace(state, tapes=SessionEventTapes(_history_len_getter(state.runtime)))
            app.state.server_state = state
        if state.tapes is not None:
            # Tap the origin bus: recording lands in the same event-loop step
            # as the fan-out, so attach replay snapshots are gap-free.
            state.event_bus.set_publish_listener(state.tapes.record)
        if state.headless is None:
            state = replace(
                state,
                headless=HeadlessRuntime(state.runtime, max_running=_headless_max_running(), tapes=state.tapes),
            )
            app.state.server_state = state
        session_live = state.session_live
        if session_live is None:
            raise RuntimeError("session live state is not initialized")
        headless = state.headless
        if headless is None:
            raise RuntimeError("headless runtime is not initialized")
        headless.start(state.event_bus)
        session_live.attach_loop(asyncio.get_running_loop())
        unregister_meta_observer = register_session_meta_observer(session_live.apply_meta_update)
        try:
            yield
        finally:
            log_debug("[server] lifespan shutdown start", debug_type=DebugType.EXECUTION)
            log_debug("[server] lifespan shutdown: closing headless runtime", debug_type=DebugType.EXECUTION)
            await headless.aclose()
            if unregister_meta_observer is not None:
                log_debug("[server] lifespan shutdown: unregister meta observer", debug_type=DebugType.EXECUTION)
                unregister_meta_observer()
            if state_initializer is not None and state_shutdown is not None:
                log_debug("[server] lifespan shutdown: state_shutdown start", debug_type=DebugType.EXECUTION)
                await state_shutdown(state)
                log_debug("[server] lifespan shutdown: state_shutdown done", debug_type=DebugType.EXECUTION)
            log_debug("[server] lifespan shutdown done", debug_type=DebugType.EXECUTION)

    app = FastAPI(title="klaude-code Server API", lifespan=_lifespan)

    has_direct_state = runtime is not None and event_bus is not None and interaction_handler is not None
    if has_direct_state and state_initializer is not None:
        raise ValueError("Pass either direct runtime state or state_initializer, not both")
    if not has_direct_state and state_initializer is None:
        raise ValueError("Server app requires runtime/event_bus/interaction_handler or state_initializer")

    if runtime is not None and event_bus is not None and interaction_handler is not None:
        resolved_home_dir = (home_dir or Path.home()).resolve()
        app.state.server_state = ServerAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=interaction_handler,
            work_dir=work_dir.resolve(),
            home_dir=resolved_home_dir,
            event_stream=event_stream,
            session_live=SessionLiveState(home_dir=resolved_home_dir, runtime=runtime),
            lifecycle=lifecycle,
            code_fingerprint=get_code_fingerprint(),
        )

    app.include_router(server_router)
    app.include_router(sessions_router)
    app.include_router(headless_router)
    app.include_router(ws_router)

    return app


def _history_len_getter(runtime: RuntimeFacade):
    def _history_len(session_id: str) -> int | None:
        actor = runtime.session_registry.get_session_actor(session_id)
        agent = actor.get_agent() if actor is not None else None
        if agent is None:
            return None
        return len(agent.session.conversation_history)

    return _history_len


def _headless_max_running() -> int:
    try:
        from klaude_code.config import load_config

        return load_config().headless_max_running
    except Exception:
        return 8
