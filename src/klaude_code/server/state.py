from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EnvelopeBus, EventBus, EventSubscription
from klaude_code.server.headless import HeadlessRuntime
from klaude_code.server.interaction import ServerInteractionHandler
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.session_live import SessionLiveState
from klaude_code.server.session_tape import SessionEventTapes


@dataclass(frozen=True)
class ServerAppState:
    runtime: RuntimeFacade
    event_bus: EventBus
    interaction_handler: ServerInteractionHandler
    work_dir: Path
    home_dir: Path
    event_stream: EnvelopeBus | None = None
    session_live: SessionLiveState | None = None
    lifecycle: ServerLifecycle | None = None
    headless: HeadlessRuntime | None = None
    tapes: SessionEventTapes | None = None
    # Frozen at startup; clients compare it against their own fingerprint.
    code_fingerprint: str = ""

    def subscribe_events(self, session_id: str | None) -> EventSubscription:
        source = self.event_stream or self.event_bus
        return source.subscribe(session_id)


def get_server_state_from_app(app: FastAPI) -> ServerAppState:
    raw_state = getattr(app.state, "server_state", None)
    if isinstance(raw_state, ServerAppState):
        return raw_state
    raise RuntimeError("Server app state is not initialized")


def get_server_state(request: Request) -> ServerAppState:
    return get_server_state_from_app(request.app)


def get_server_state_from_ws(websocket: WebSocket) -> ServerAppState:
    return get_server_state_from_app(websocket.app)
