from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EnvelopeBus, EventBus
from klaude_code.control.session_meta_relay import (
    SessionMetaRelayMessage,
    SessionMetaRelayServer,
    session_meta_relay_socket_path,
)
from klaude_code.log import DebugType, log_debug
from klaude_code.session.store import register_session_meta_observer
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.routes import config_router, files_router, sessions_router, skills_router, ws_router
from klaude_code.web.session_live import SessionLiveState
from klaude_code.web.state import WebAppState, get_web_state_from_app


def resolve_static_dir() -> Path | None:
    module_dir = Path(__file__).resolve().parent
    candidates = [
        module_dir / "dist",
        module_dir.parents[3] / "web" / "dist",
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


def create_app(
    *,
    runtime: RuntimeFacade | None = None,
    event_bus: EventBus | None = None,
    event_stream: EnvelopeBus | None = None,
    interaction_handler: WebInteractionHandler | None = None,
    work_dir: Path,
    home_dir: Path | None = None,
    static_dir: Path | None = None,
    state_initializer: Callable[[], Awaitable[WebAppState]] | None = None,
    state_shutdown: Callable[[WebAppState], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        unregister_meta_observer: Callable[[], None] | None = None
        session_meta_relay_server: SessionMetaRelayServer | None = None
        if state_initializer is not None:
            app.state.web_state = await state_initializer()
        state = get_web_state_from_app(app)
        if state.session_live is None:
            state = replace(state, session_live=SessionLiveState(home_dir=state.home_dir, runtime=state.runtime))
            app.state.web_state = state
        session_live = state.session_live
        if session_live is None:
            raise RuntimeError("session live state is not initialized")
        session_live.attach_loop(asyncio.get_running_loop())
        unregister_meta_observer = register_session_meta_observer(session_live.apply_meta_update)
        session_meta_relay_server = SessionMetaRelayServer(
            socket_path=session_meta_relay_socket_path(home_dir=state.home_dir),
            on_message=lambda message: _apply_session_meta_message(session_live, message),
        )
        await session_meta_relay_server.start()
        try:
            yield
        finally:
            log_debug("[web] lifespan shutdown start", debug_type=DebugType.EXECUTION)
            log_debug("[web] lifespan shutdown: closing session meta relay", debug_type=DebugType.EXECUTION)
            await session_meta_relay_server.aclose()
            log_debug("[web] lifespan shutdown: session meta relay closed", debug_type=DebugType.EXECUTION)
            if unregister_meta_observer is not None:
                log_debug("[web] lifespan shutdown: unregister meta observer", debug_type=DebugType.EXECUTION)
                unregister_meta_observer()
            if state_initializer is not None and state_shutdown is not None:
                log_debug("[web] lifespan shutdown: state_shutdown start", debug_type=DebugType.EXECUTION)
                await state_shutdown(state)
                log_debug("[web] lifespan shutdown: state_shutdown done", debug_type=DebugType.EXECUTION)
            log_debug("[web] lifespan shutdown done", debug_type=DebugType.EXECUTION)

    app = FastAPI(title="klaude-code Web API", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    has_direct_state = runtime is not None and event_bus is not None and interaction_handler is not None
    if has_direct_state and state_initializer is not None:
        raise ValueError("Pass either direct runtime state or state_initializer, not both")
    if not has_direct_state and state_initializer is None:
        raise ValueError("Web app requires runtime/event_bus/interaction_handler or state_initializer")

    if runtime is not None and event_bus is not None and interaction_handler is not None:
        resolved_home_dir = (home_dir or Path.home()).resolve()
        app.state.web_state = WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=interaction_handler,
            work_dir=work_dir.resolve(),
            home_dir=resolved_home_dir,
            event_stream=event_stream,
            session_live=SessionLiveState(home_dir=resolved_home_dir, runtime=runtime),
        )

    app.include_router(sessions_router)
    app.include_router(config_router)
    app.include_router(files_router)
    app.include_router(skills_router)
    app.include_router(ws_router)

    static_root = static_dir or resolve_static_dir()
    if static_root is not None:
        app.mount("/", StaticFiles(directory=str(static_root), html=True), name="web-static")
    else:

        @app.get("/")
        async def root() -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
            return JSONResponse(
                status_code=503,
                content={
                    "ok": False,
                    "message": "Web frontend assets are missing. Build web/dist first.",
                },
            )

    return app


def _apply_session_meta_message(session_live: SessionLiveState, message: SessionMetaRelayMessage) -> None:
    if message.kind == "delete":
        session_live.apply_deleted(message.session_id)
        return
    if message.meta is None:
        return
    session_live.apply_meta_update(message.session_id, message.meta)
