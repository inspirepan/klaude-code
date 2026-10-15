"""Peer delivery through the existing session index and input scheduler."""

from pathlib import Path

from fastapi import HTTPException

from klaude_code.protocol.peer import PeerInfo, PeerMessage, PeerReceipt
from klaude_code.server.routes.headless import (
    _headless_state,
    _load_summaries,
    _require_admission,
    _require_headless,
    _resolve_target,
    _sanitize_sender_label,
)
from klaude_code.server.state import ServerAppState


def wire_peers(state: ServerAppState) -> None:
    async def list_peers(sender: str, work_dir: Path) -> list[PeerInfo]:
        headless = _require_headless(state)
        live = {actor.session_id for actor in state.runtime.session_registry.list_session_actors()}
        return [
            PeerInfo(
                session_id=summary.id,
                name=summary.name,
                state=_headless_state(state, headless, summary.id),
                description=summary.title or "",
                work_dir=summary.work_dir,
            )
            for summary in _load_summaries(state)
            if summary.id != sender
            and Path(summary.work_dir).resolve() == work_dir.resolve()
            and not summary.archived
            and (summary.id in live or headless.has_pending(summary.id))
        ]

    async def send_peer(sender: str, target: str, body: str, reply_to: str | None) -> PeerReceipt:
        try:
            _require_admission(state)
            summaries = _load_summaries(state)
            origin = next((summary for summary in summaries if summary.id == sender), None)
            if origin is None:
                raise ValueError("Sender session is unavailable")
            recipient = _resolve_target(summaries, target)
            peer = PeerMessage(
                sender_session_id=origin.id,
                sender_label=_sanitize_sender_label(origin.name or origin.id),
                recipient=recipient.id,
                body=body,
                reply_to=reply_to,
            )
            return await _require_headless(state).deliver_peer(peer, Path(recipient.work_dir))
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc

    state.runtime.peer_control.list_callback = list_peers
    state.runtime.peer_control.send_callback = send_peer
