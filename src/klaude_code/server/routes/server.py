from __future__ import annotations

import os
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from klaude_code.app.runtime_facade import RuntimeFacade
from klaude_code.server.lifecycle import ServerLifecycle
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


def list_active_sessions(runtime: RuntimeFacade) -> list[dict[str, str]]:
    """Sessions with live work: running tasks or pending interaction requests."""

    active: list[dict[str, str]] = []
    for actor in runtime.session_registry.list_session_actors():
        snapshot = actor.snapshot()
        if snapshot.pending_request_count > 0:
            state = "waiting_input"
        elif snapshot.active_root_task is not None or snapshot.child_task_count > 0:
            state = "running"
        else:
            continue
        active.append({"session_id": actor.session_id, "state": state})
    return active


@router.get("/status")
async def server_status(state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    lifecycle = _require_lifecycle(state)
    active_sessions = list_active_sessions(state.runtime)
    return {
        "ok": True,
        "pid": os.getpid(),
        "version": get_display_version(),
        "socket_path": str(lifecycle.socket_path),
        "uptime_seconds": lifecycle.uptime_seconds,
        "sessions": {
            "loaded": len(state.runtime.session_registry.list_session_actors()),
            "running": sum(1 for item in active_sessions if item["state"] == "running"),
            "waiting_input": sum(1 for item in active_sessions if item["state"] == "waiting_input"),
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
    active_sessions = list_active_sessions(state.runtime)
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
