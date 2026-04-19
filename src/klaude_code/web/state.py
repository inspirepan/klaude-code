from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.control.event_bus import EnvelopeBus, EventBus, EventSubscription
from klaude_code.web.interaction import WebInteractionHandler
from klaude_code.web.session_live import SessionLiveState


@dataclass(frozen=True)
class WebAppState:
    runtime: RuntimeFacade
    event_bus: EventBus
    interaction_handler: WebInteractionHandler
    work_dir: Path
    home_dir: Path
    event_stream: EnvelopeBus | None = None
    session_live: SessionLiveState | None = None

    def subscribe_events(self, session_id: str | None) -> EventSubscription:
        source = self.event_stream or self.event_bus
        return source.subscribe(session_id)

def get_web_state_from_app(app: FastAPI) -> WebAppState:
    raw_state = getattr(app.state, "web_state", None)
    if isinstance(raw_state, WebAppState):
        return raw_state
    raise RuntimeError("Web app state is not initialized")

def get_web_state(request: Request) -> WebAppState:
    return get_web_state_from_app(request.app)

def get_web_state_from_ws(websocket: WebSocket) -> WebAppState:
    return get_web_state_from_app(websocket.app)
