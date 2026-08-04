from __future__ import annotations

import os
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.session_state import derive_session_state_from_snapshot
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.update import get_display_version

router = APIRouter(prefix="/api/server", tags=["server"])
_SERVER_STATE_DEP: Final = Depends(get_server_state)


class ReloadRequest(BaseModel):
    force: bool = False


def _require_lifecycle(state: ServerAppState) -> ServerLifecycle:
    if state.lifecycle is None:
        raise HTTPException(status_code=503, detail="Server lifecycle is not available")
    return state.lifecycle


def list_active_sessions(state: ServerAppState) -> list[dict[str, str]]:
    """Sessions with live work: running tasks, pending interactions, or queued runs."""

    active: list[dict[str, str]] = []
    for actor in state.runtime.session_registry.list_session_actors():
        actor_state = derive_session_state_from_snapshot(actor.snapshot())
        if actor_state == "waiting_user_input":
            active.append({"session_id": actor.session_id, "state": "waiting_input"})
        elif actor_state == "running":
            active.append({"session_id": actor.session_id, "state": "running"})
    if state.headless is not None:
        seen = {item["session_id"] for item in active}
        for session_id in state.headless.queued_session_ids():
            if session_id not in seen:
                active.append({"session_id": session_id, "state": "queued"})
    return active


@router.get("/status")
async def server_status(state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    lifecycle = _require_lifecycle(state)
    active_sessions = list_active_sessions(state)
    return {
        "ok": True,
        "pid": os.getpid(),
        "version": get_display_version(),
        "protocol_version": PROTOCOL_VERSION,
        "code_fingerprint": state.code_fingerprint,
        "socket_path": str(lifecycle.socket_path),
        "uptime_seconds": lifecycle.uptime_seconds,
        "sessions": {
            "loaded": len(state.runtime.session_registry.list_session_actors()),
            "running": sum(1 for item in active_sessions if item["state"] == "running"),
            "waiting_input": sum(1 for item in active_sessions if item["state"] == "waiting_input"),
            "queued": sum(1 for item in active_sessions if item["state"] == "queued"),
        },
    }


@router.post("/stop")
async def server_stop(state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    lifecycle = _require_lifecycle(state)
    # Shutdown is graceful: the serve loop exits, then runtime cleanup
    # interrupts running agents and waits for session flush to disk.
    lifecycle.request_stop()
    return {"ok": True, "pid": os.getpid()}


@router.post("/reload")
async def server_reload(request: ReloadRequest, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    lifecycle = _require_lifecycle(state)
    active_sessions = list_active_sessions(state)
    if active_sessions and not request.force:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Sessions are still active; pass --force to interrupt them",
                "sessions": active_sessions,
            },
        )
    lifecycle.request_reload()
    return {"ok": True, "pid": os.getpid(), "interrupted": active_sessions}
