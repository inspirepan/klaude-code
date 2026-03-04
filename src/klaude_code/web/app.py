from __future__ import annotations

import sysconfig
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from klaude_code.core.control.event_bus import EventBus
from klaude_code.core.control.runtime_facade import RuntimeFacade
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.routes import config_router, files_router, sessions_router, ws_router
from klaude_code.web.state import WebAppState, get_web_state_from_app


def resolve_static_dir() -> Path | None:
    module_dir = Path(__file__).resolve().parent
    repo_root = module_dir.parents[3]

    candidates = [
        repo_root / "web" / "dist",
        module_dir / "dist",
        Path(sysconfig.get_path("data")),
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / "index.html").exists():
            return candidate
    return None


def create_app(
    *,
    runtime: RuntimeFacade | None = None,
    event_bus: EventBus | None = None,
    interaction_handler: WebInteractionHandler | None = None,
    work_dir: Path,
    home_dir: Path | None = None,
    static_dir: Path | None = None,
    state_initializer: Callable[[], Awaitable[WebAppState]] | None = None,
    state_shutdown: Callable[[WebAppState], Awaitable[None]] | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        if state_initializer is not None:
            app.state.web_state = await state_initializer()
        try:
            yield
        finally:
            if state_initializer is not None and state_shutdown is not None:
                state = get_web_state_from_app(app)
                await state_shutdown(state)

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
        app.state.web_state = WebAppState(
            runtime=runtime,
            event_bus=event_bus,
            interaction_handler=interaction_handler,
            work_dir=work_dir.resolve(),
            home_dir=(home_dir or Path.home()).resolve(),
        )

    app.include_router(sessions_router)
    app.include_router(config_router)
    app.include_router(files_router)
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
