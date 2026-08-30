"""Read-only REST surface for the web viewer's ledger.

Everything here reads from disk: a cold session is served straight out of its
``events.jsonl`` without initializing an agent (plan decision #28). The ledger
is the raw jsonl — one row per physical line, keyed by a zero-based
``line_index`` — plus the per-line status the shared scan derives
(``session/history.py``), so the client never replays rebuild logic.

Registered before the static routes so ``/api/web/...`` wins over the bundle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response

from klaude_code.const import get_system_temp
from klaude_code.server.routes.headless import session_state_for
from klaude_code.server.session_index import resolve_session_work_dir_fast
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.session.store import JsonlSessionStore
from klaude_code.session.store_registry import get_store_for_path
from klaude_code.workspace import resolve_workspace_path

router = APIRouter(prefix="/api/web", tags=["web-api"])
_STATE_DEP: Final = Depends(get_server_state)

DEFAULT_HISTORY_LIMIT: Final = 500
MAX_HISTORY_LIMIT: Final = 2000

# Raster images only. SVG is scriptable and would run in the viewer's origin,
# so it is refused rather than served with a defused content type.
_IMAGE_MEDIA_TYPES: Final = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
MAX_FILE_BYTES: Final = 25 * 1024 * 1024


@dataclass(frozen=True)
class _SessionRef:
    session_id: str
    work_dir: Path
    store: JsonlSessionStore
    meta: dict[str, Any]


def _resolve_session(state: ServerAppState, session_id: str) -> _SessionRef:
    """Locate a session on disk without touching the runtime.

    The live index answers first; the fallback scan finds sessions the index
    hides or has not seen (created by another process since startup).
    """
    index = state.session_live.index if state.session_live is not None else None
    work_dir = resolve_session_work_dir_fast(index, state.home_dir, session_id)
    if work_dir is None:
        raise HTTPException(status_code=404, detail="session not found")
    store = get_store_for_path(work_dir)
    return _SessionRef(session_id=session_id, work_dir=work_dir, store=store, meta=store.load_meta(session_id) or {})


def _optional_str(meta: dict[str, Any], key: str) -> str | None:
    value = meta.get(key)
    return value if isinstance(value, str) and value else None


def _optional_float(meta: dict[str, Any], key: str) -> float | None:
    value = meta.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except ValueError:
        return None


@router.get("/sessions/{session_id}/meta")
async def get_session_meta(session_id: str, state: ServerAppState = _STATE_DEP) -> dict[str, Any]:
    ref = _resolve_session(state, session_id)
    line_count = await asyncio.to_thread(ref.store.history_line_count, session_id)
    return {
        "session_id": session_id,
        "title": _optional_str(ref.meta, "title"),
        "work_dir": str(ref.work_dir),
        "model": _optional_str(ref.meta, "model_config_name") or _optional_str(ref.meta, "model_name"),
        "parent_session_id": _optional_str(ref.meta, "parent_session_id"),
        "created_at": _optional_float(ref.meta, "created_at"),
        "updated_at": _optional_float(ref.meta, "updated_at"),
        "state": session_state_for(state, session_id),
        # False means "no agent in memory": the ledger below still answers,
        # and asking for it never spins one up.
        "loaded": state.runtime.session_registry.has_session_actor(session_id),
        "line_count": line_count,
    }


@router.get("/sessions/{session_id}/history")
async def get_session_history(
    session_id: str,
    before_line: int | None = None,
    after_line: int | None = None,
    limit: int = DEFAULT_HISTORY_LIMIT,
    state: ServerAppState = _STATE_DEP,
) -> dict[str, Any]:
    if before_line is not None and after_line is not None:
        raise HTTPException(status_code=400, detail="before_line and after_line are mutually exclusive")
    ref = _resolve_session(state, session_id)
    clamped = max(1, min(limit, MAX_HISTORY_LIMIT))
    return await asyncio.to_thread(
        _read_history_page,
        ref.store,
        session_id,
        before_line,
        after_line,
        clamped,
    )


def _read_history_page(
    store: JsonlSessionStore,
    session_id: str,
    before_line: int | None,
    after_line: int | None,
    limit: int,
) -> dict[str, Any]:
    line_count = store.history_line_count(session_id)
    if after_line is not None:
        # Tail increment: the first `limit` lines strictly after the anchor.
        start = min(max(after_line + 1, 0), line_count)
        end = min(start + limit, line_count)
        has_more = end < line_count
        next_before_line = None
    else:
        # Tail page, or the `limit` lines strictly before the anchor.
        end = line_count if before_line is None else max(min(before_line, line_count), 0)
        start = max(end - limit, 0)
        has_more = start > 0
        next_before_line = start if end > start else None

    # Statuses depend on marker lines further down the file, so the scan always
    # covers the whole file (cached per stat stamp) and the page slices it.
    statuses = store.scan_history_lines(session_id).statuses
    rows: list[dict[str, Any]] = []
    for line_index, entry in store.encode_history_lines(session_id, start, end):
        status = statuses[line_index] if 0 <= line_index < len(statuses) else None
        rows.append(
            {
                "line_index": line_index,
                "status": status.status if status is not None else "unknown",
                "dropped_by": status.dropped_by if status is not None else None,
                "entry": entry,
            }
        )
    return {
        "session_id": session_id,
        "line_count": line_count,
        "rows": rows,
        "has_more": has_more,
        "next_before_line": next_before_line,
    }


def _allowed_file_roots(ref: _SessionRef) -> tuple[Path, ...]:
    """The three roots a session may legitimately reference an image from.

    Its work_dir (model/user file references), its own content-addressed image
    directory (frozen history images), and the system temp dir where clipboard
    captures land (``tui/input/images.py``).
    """
    return (
        ref.work_dir.resolve(),
        ref.store.paths.images_dir(ref.session_id).resolve(),
        Path(get_system_temp()).resolve(),
    )


@router.get("/file")
async def get_local_file(session_id: str, path: str, state: ServerAppState = _STATE_DEP) -> Response:
    ref = _resolve_session(state, session_id)
    try:
        # Resolves symlinks, so an escaping link fails the containment check
        # below rather than being followed out of the allowed roots.
        target = resolve_workspace_path(path, ref.work_dir)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="invalid path") from None
    if not any(target.is_relative_to(root) for root in _allowed_file_roots(ref)):
        raise HTTPException(status_code=403, detail="path is outside the session's readable roots")
    media_type = _IMAGE_MEDIA_TYPES.get(target.suffix.lower())
    if media_type is None:
        raise HTTPException(status_code=415, detail="only png/jpg/jpeg/gif/webp files are served")
    try:
        stat = target.stat()
    except OSError:
        raise HTTPException(status_code=404, detail="file not found") from None
    if not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    if stat.st_size > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file is larger than the viewer's 25 MB cap")
    return FileResponse(
        target,
        media_type=media_type,
        headers={"Cache-Control": "private, max-age=60", "X-Content-Type-Options": "nosniff"},
    )
