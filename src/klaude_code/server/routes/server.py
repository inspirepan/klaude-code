from __future__ import annotations

import os
from typing import Any, Final, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.server.binding import web_url
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.session_state import derive_session_state_from_snapshot
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.server.upgrade import UpgradeCoordinator
from klaude_code.update import get_display_version

router = APIRouter(prefix="/api/server", tags=["server"])
_SERVER_STATE_DEP: Final = Depends(get_server_state)


class ReloadRequest(BaseModel):
    force: bool = False
    # "idle": register with the upgrade coordinator and restart at the next
    # idle boundary instead of refusing a busy server.
    when: Literal["now", "idle"] = "now"


class UpgradeRequest(BaseModel):
    # Re-check upstream before installing (manual `klaude upgrade`); otherwise
    # the persisted result of the last background check decides.
    check: bool = False


class DebugRequest(BaseModel):
    enabled: bool = True


def _require_lifecycle(state: ServerAppState) -> ServerLifecycle:
    if state.lifecycle is None:
        raise HTTPException(status_code=503, detail="Server lifecycle is not available")
    return state.lifecycle


def _require_upgrade(state: ServerAppState) -> UpgradeCoordinator:
    if state.upgrade is None:
        raise HTTPException(status_code=503, detail="Server upgrade coordinator is not available")
    return state.upgrade


def list_active_sessions(state: ServerAppState) -> list[dict[str, str]]:
    """Sessions with live work: running tasks, pending interactions, or queued runs."""

    active: list[dict[str, str]] = []
    for actor in state.runtime.session_registry.list_session_actors():
        actor_state = derive_session_state_from_snapshot(actor.snapshot())
        if actor_state == "waiting_user_input":
            active.append({"session_id": actor.session_id, "state": "waiting_input"})
        elif actor_state == "running":
            active.append({"session_id": actor.session_id, "state": "running"})
        elif state.headless is not None and state.headless.has_live_follow_ups(actor.session_id):
            # The drain starts the next turn as soon as this one ends; a reload
            # in between would strand the queue until the client reattaches.
            active.append({"session_id": actor.session_id, "state": "queued"})
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
        # None when no loopback port could be bound; `klaude trace` reports that.
        "web_port": state.web_port,
        "web_url": web_url(state.web_port) if state.web_port is not None else None,
        "uptime_seconds": lifecycle.uptime_seconds,
        "sessions": {
            "loaded": len(state.runtime.session_registry.list_session_actors()),
            "running": sum(1 for item in active_sessions if item["state"] == "running"),
            "waiting_input": sum(1 for item in active_sessions if item["state"] == "waiting_input"),
            "queued": sum(1 for item in active_sessions if item["state"] == "queued"),
        },
        "upgrade": state.upgrade.status() if state.upgrade is not None else None,
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
    if request.force:
        lifecycle.request_reload()
        return {"ok": True, "pid": os.getpid(), "state": "reloading", "interrupted": active_sessions}
    if request.when == "idle":
        status = _require_upgrade(state).request("reload")
        return {
            "ok": True,
            "pid": os.getpid(),
            "state": status["phase"],
            "sessions": active_sessions,
            "upgrade": status,
            "interrupted": [],
        }
    if active_sessions:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Sessions are still active; pass --force to interrupt them or --when-idle to wait",
                "sessions": active_sessions,
            },
        )
    lifecycle.request_reload()
    return {"ok": True, "pid": os.getpid(), "state": "reloading", "interrupted": []}


@router.get("/upgrade")
async def server_upgrade_status(state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    return {"ok": True, "pid": os.getpid(), **_require_upgrade(state).status()}


@router.post("/upgrade")
async def server_upgrade(request: UpgradeRequest, state: ServerAppState = _SERVER_STATE_DEP) -> dict[str, Any]:
    """Install the latest code and restart, once no session has live work.

    The server owns the install so no running turn ever executes on a
    half-replaced venv; a busy server keeps the request pending.
    """

    status = _require_upgrade(state).request("upgrade", check=request.check)
    return {"ok": True, "pid": os.getpid(), **status}


@router.post("/debug")
async def server_debug(request: DebugRequest) -> dict[str, Any]:
    """Enable or disable debug file logging in the server process.

    Debug logging is on by default in the server process; this endpoint is
    the off switch. Client-side ``--debug`` flips it here rather than
    creating an empty local log file, since agent/LLM work lives here.
    """
    from klaude_code.log import get_current_log_file, is_debug_enabled, set_debug_logging

    set_debug_logging(request.enabled, write_to_file=True)
    log_file = get_current_log_file()
    return {
        "ok": True,
        "enabled": is_debug_enabled(),
        "log_file": str(log_file) if log_file is not None else None,
    }


@router.post("/config/reload")
async def server_config_reload() -> dict[str, Any]:
    """Drop the cached config so the next read picks up the file on disk.

    ``load_config`` caches for the whole process, so a client that edits
    ~/.klaude/klaude-config.yaml (e.g. /manage-providers) would otherwise not
    affect server-side sessions until the server re-execs. Live LLM clients keep
    the model they were built with; only later resolutions see the new config.
    """
    from klaude_code.config import load_config

    load_config.cache_clear()
    try:
        load_config()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "pid": os.getpid()}
