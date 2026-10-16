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
from klaude_code.server.session_index import SessionSummary
from klaude_code.server.state import ServerAppState


def wire_peers(state: ServerAppState) -> None:
    def reachable(summary: SessionSummary, sender: str, sender_parent: str | None, work_dir: Path) -> bool:
        """Whether `sender` may address `summary`: what ListPeers shows, plus its own parent and children.

        MessagePeer must not reach further than discovery, or it would revive
        reaped, archived, or other-workspace sessions by ID.
        """
        if summary.id == sender or summary.archived:
            return False
        if summary.id == sender_parent or summary.parent_session_id == sender:
            return True
        headless = _require_headless(state)
        live = {actor.session_id for actor in state.runtime.session_registry.list_session_actors()}
        return Path(summary.work_dir).resolve() == work_dir.resolve() and (
            summary.id in live or headless.has_pending(summary.id)
        )

    async def list_peers(sender: str, work_dir: Path) -> list[PeerInfo]:
        headless = _require_headless(state)
        summaries = _load_summaries(state)
        origin = next((summary for summary in summaries if summary.id == sender), None)
        sender_parent = origin.parent_session_id if origin is not None else None
        return [
            PeerInfo(
                session_id=summary.id,
                name=summary.name,
                state=_headless_state(state, headless, summary.id),
                description=summary.title or "",
                work_dir=summary.work_dir,
            )
            for summary in summaries
            if reachable(summary, sender, sender_parent, work_dir)
        ]

    async def send_peer(sender: str, target: str, body: str, reply_to: str | None) -> PeerReceipt:
        try:
            _require_admission(state)
            summaries = _load_summaries(state)
            origin = next((summary for summary in summaries if summary.id == sender), None)
            if origin is None:
                raise ValueError("Sender session is unavailable")
            candidates = [
                summary
                for summary in summaries
                if reachable(summary, origin.id, origin.parent_session_id, Path(origin.work_dir))
            ]
            recipient = _resolve_target(candidates, target)
            peer = PeerMessage(
                sender_session_id=origin.id,
                sender_label=_sanitize_sender_label(origin.name or origin.title or origin.id),
                recipient=recipient.id,
                body=body,
                reply_to=reply_to,
            )
            return await _require_headless(state).deliver_peer(peer, Path(recipient.work_dir))
        except HTTPException as exc:
            raise ValueError(str(exc.detail)) from exc

    state.runtime.peer_control.list_callback = list_peers
    state.runtime.peer_control.send_callback = send_peer
