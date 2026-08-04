from __future__ import annotations

from pathlib import Path
from typing import Final
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from klaude_code.protocol import op
from klaude_code.server.session_index import resolve_session_work_dir
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.session.session import Session
from klaude_code.session.store_registry import get_store_for_path

router = APIRouter(prefix="/api/sessions", tags=["sessions"])
_SERVER_STATE_DEP: Final = Depends(get_server_state)


class CreateSessionRequest(BaseModel):
    work_dir: str | None = None
    model: str | None = None
    vanilla: bool = False


class ModelConfigRequest(BaseModel):
    model_name: str


@router.post("")
async def create_session(
    payload: CreateSessionRequest,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, str]:
    target_work_dir = Path(payload.work_dir).expanduser() if payload.work_dir else state.work_dir
    if not target_work_dir.exists() or not target_work_dir.is_dir():
        raise HTTPException(status_code=400, detail=f"work_dir does not exist: {target_work_dir}")
    target_work_dir = target_work_dir.resolve()

    if payload.model is not None:
        from klaude_code.config import load_config

        try:
            config = load_config()
            candidates = config.iter_model_config_candidates(payload.model)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"unknown model '{payload.model}': {exc}") from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to load config: {exc}") from exc
        if not candidates:
            raise HTTPException(status_code=400, detail=f"model '{payload.model}' is unavailable")

    # Persist meta first (model/vanilla are read when the agent is built),
    # then spin up the actor so follow-up REST/WS calls find it.
    session = Session.create(id=uuid4().hex, work_dir=target_work_dir)
    session.model_config_name = payload.model
    session.vanilla = payload.vanilla
    try:
        session.ensure_meta_exists()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session metadata: {exc}") from exc

    try:
        await state.runtime.submit_and_wait(
            op.InitAgentOperation(
                session_id=session.id,
                work_dir=target_work_dir,
                defer_welcome_context=True,
                defer_replay=True,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to create session: {exc}") from exc
    return {"session_id": session.id}


def _check_write_access(state: ServerAppState, session_id: str) -> Path:
    """Validate the session exists; return its work_dir or raise 404."""
    work_dir = resolve_session_work_dir(state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")
    return work_dir


@router.put("/{session_id}/model/config")
async def configure_session_model(
    session_id: str,
    payload: ModelConfigRequest,
    state: ServerAppState = _SERVER_STATE_DEP,
) -> dict[str, bool]:
    """Set the model used by the next actor rehydrate."""
    work_dir = _check_write_access(state, session_id)
    if state.headless is not None and state.headless.has_pending(session_id):
        raise HTTPException(status_code=409, detail="session has pending headless work")

    actor = state.runtime.session_registry.get_session_actor(session_id)
    if actor is not None:
        if not actor.snapshot().is_idle:
            raise HTTPException(status_code=409, detail="session is active")
        if not await state.runtime.close_session(session_id):
            raise HTTPException(status_code=409, detail="session became active")

    updated = get_store_for_path(work_dir).update_meta(session_id, {"model_config_name": payload.model_name})
    if not updated:
        raise HTTPException(status_code=500, detail="failed to update session model")
    return {"ok": True}
