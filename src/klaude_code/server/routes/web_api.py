"""Read-only REST surface for the web viewer's ledger.

Everything here reads from disk: a cold session is served straight out of its
``events.jsonl`` without initializing an agent (plan decision #28). The ledger
is the raw jsonl — one row per physical line, keyed by a zero-based
``line_index`` — plus the per-line status the shared scan derives
(``session/history.py``) and the turn/step ordinals the ledger scan derives
(``session/ledger.py``), so the client never replays rebuild logic.

Registered before the static routes so ``/api/web/...`` wins over the bundle.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from klaude_code.const import get_system_temp
from klaude_code.server import system_context
from klaude_code.server.routes.headless import session_state_for
from klaude_code.server.session_index import resolve_session_work_dir_fast
from klaude_code.server.state import ServerAppState, get_server_state
from klaude_code.session import search
from klaude_code.session.store import JsonlSessionStore
from klaude_code.session.store_registry import get_store_for_path
from klaude_code.workspace import resolve_workspace_path

router = APIRouter(prefix="/api/web", tags=["web-api"])
_STATE_DEP: Final = Depends(get_server_state)

DEFAULT_HISTORY_LIMIT: Final = 500
MAX_HISTORY_LIMIT: Final = 2000
DEFAULT_SEARCH_LIMIT: Final = 200
MAX_SEARCH_LIMIT: Final = 2000

# Required, non-empty and bounded: a query is scanned against every line, so an
# unbounded one would be a cheap way to make the server chew through the file.
_QUERY_PARAM: Final = Query(min_length=1, max_length=search.MAX_QUERY_CHARS)

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

    # Statuses depend on marker lines further down the file, and turn/step
    # ordinals count from line 0, so both scans always cover the whole file
    # (cached per stat stamp) and the page slices them. The client must never
    # renumber from the window it holds — prepending an older page would shift
    # every ordinal it already showed.
    statuses = store.scan_history_lines(session_id).statuses
    ordinals = store.scan_turn_ordinals(session_id)
    rows: list[dict[str, Any]] = []
    for line_index, entry in store.encode_history_lines(session_id, start, end):
        status = statuses[line_index] if 0 <= line_index < len(statuses) else None
        ordinal = ordinals.for_line(line_index)
        rows.append(
            {
                "line_index": line_index,
                "status": status.status if status is not None else "unknown",
                "dropped_by": status.dropped_by if status is not None else None,
                "turn_index": ordinal.turn_index,
                "step_index": ordinal.step_index,
                "auto": ordinal.auto,
                "entry": entry,
            }
        )
    return {
        "session_id": session_id,
        "line_count": line_count,
        "turn_count": ordinals.turn_count,
        "rows": rows,
        "has_more": has_more,
        "next_before_line": next_before_line,
    }


@router.get("/sessions/{session_id}/children")
async def get_session_children(session_id: str, state: ServerAppState = _STATE_DEP) -> dict[str, Any]:
    """The sub-agents this session spawned, as its own ledger recorded them.

    The session list nests children under their parent, but a child's meta only
    carries its ``agent_type`` — the description the parent wrote when
    delegating lives in the parent's ``SpawnSubAgentEntry`` rows and nowhere
    else. A parent with no sub-agents answers with an empty list.
    """
    ref = _resolve_session(state, session_id)
    children = await asyncio.to_thread(_spawned_children, ref.store, session_id)
    return {"session_id": session_id, "children": children}


def _spawned_children(store: JsonlSessionStore, session_id: str) -> list[dict[str, Any]]:
    """Spawn rows in file order, first row winning for a repeated child id.

    A child id can be recorded twice (a replayed spawn, a hand-edited ledger);
    the first row is the one that describes the delegation that created it.
    """
    seen: set[str] = set()
    children: list[dict[str, Any]] = []
    for line_index, entry in store.scan_spawned_sub_agents(session_id):
        if entry.session_id in seen:
            continue
        seen.add(entry.session_id)
        children.append(
            {
                "session_id": entry.session_id,
                "sub_agent_type": entry.sub_agent_type,
                "sub_agent_desc": entry.sub_agent_desc,
                "model": entry.model,
                # ISO 8601, matching how the history endpoint encodes datetimes.
                "created_at": entry.created_at.isoformat(),
                "line_index": line_index,
            }
        )
    return children


@router.get("/sessions/{session_id}/search")
async def search_session_history(
    session_id: str,
    q: str = _QUERY_PARAM,
    limit: int = DEFAULT_SEARCH_LIMIT,
    state: ServerAppState = _STATE_DEP,
) -> dict[str, Any]:
    """Term search over the whole ledger, including the lines nobody loaded.

    The client live-filters the rows it already holds (plan decision #22); this
    answers for the rest and returns ``line_index`` so it can jump there. The
    text semantics match the client's index — lowercase, whitespace-split, AND
    over substrings — so a hit here still matches once that page is on screen.
    """
    ref = _resolve_session(state, session_id)
    terms = search.split_terms(q)
    if not terms:
        raise HTTPException(status_code=422, detail="q must contain at least one search term")
    clamped = max(1, min(limit, MAX_SEARCH_LIMIT))
    return await asyncio.to_thread(_search_history, ref.store, session_id, q, terms, clamped)


def _search_history(
    store: JsonlSessionStore,
    session_id: str,
    query: str,
    terms: list[str],
    limit: int,
) -> dict[str, Any]:
    scan = store.search_history(session_id, terms, limit)
    # Same whole-file scans the paging endpoint slices: a jump target needs the
    # status (greyed out or not) and the turn it belongs to.
    statuses = store.scan_history_lines(session_id).statuses
    ordinals = store.scan_turn_ordinals(session_id)
    matches: list[dict[str, Any]] = []
    for hit in scan.hits:
        status = statuses[hit.line_index] if 0 <= hit.line_index < len(statuses) else None
        matches.append(
            {
                "line_index": hit.line_index,
                "turn_index": ordinals.for_line(hit.line_index).turn_index,
                "kind": hit.kind,
                "status": status.status if status is not None else "unknown",
                "snippet": search.snippet_for(hit.text, terms),
            }
        )
    return {
        "session_id": session_id,
        "query": query,
        "terms": terms,
        "matches": matches,
        "total": scan.total,
        "truncated": scan.total > limit,
    }


@router.get("/sessions/{session_id}/system-context")
async def get_session_system_context(session_id: str, state: ServerAppState = _STATE_DEP) -> dict[str, Any]:
    """The system prompt, tool catalogue and model knobs behind the SYSTEM row.

    A loaded session answers from its live profile. A cold one is rebuilt from
    meta with the same builders the agent uses -- read-only, and labelled
    ``rebuilt`` because it reflects today's prompt files rather than what was
    sent back then. Answers are cached per session for 30s.
    """
    ref = _resolve_session(state, session_id)
    hit = system_context.cached(session_id)
    if hit is not None:
        return hit

    actor = state.runtime.session_registry.get_session_actor(session_id)
    agent = actor.get_agent() if actor is not None else None
    if agent is not None:
        payload = system_context.live_payload(agent.profile, model_config_name=agent.session.model_config_name)
    else:
        # Prompt assembly reads prompt files and stats the work_dir; keep it off
        # the event loop.
        payload = await asyncio.to_thread(system_context.rebuilt_payload, ref.meta, ref.work_dir)
    return system_context.store(session_id, payload)


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
