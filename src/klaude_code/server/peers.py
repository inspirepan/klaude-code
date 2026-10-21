"""Peer delivery through the existing session index and input scheduler."""

import asyncio
from pathlib import Path
from time import time

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
from klaude_code.session.store_registry import get_store_for_path


def wire_peers(state: ServerAppState) -> None:
    def reachable(summary: SessionSummary, sender: str, sender_parent: str | None, work_dir: Path) -> bool:
        """Whether `sender` may address `summary`, using the same rules as ListPeers.

        MessagePeer must not reach further than discovery, or it would revive
        reaped, archived, or other-workspace sessions by ID.
        """
        if summary.id == sender or summary.archived:
            return False
        headless = _require_headless(state)
        if _headless_state(state, headless, summary.id) == "idle" and summary.updated_at < time() - 24 * 60 * 60:
            return False
        if summary.id == sender_parent or summary.parent_session_id == sender:
            return True
        live = {actor.session_id for actor in state.runtime.session_registry.list_session_actors()}
        return Path(summary.work_dir).resolve() == work_dir.resolve() and (
            summary.id in live or headless.has_pending(summary.id)
        )

    async def list_peers(sender: str, work_dir: Path) -> list[PeerInfo]:
        headless = _require_headless(state)
        summaries = _load_summaries(state)
        origin = next((summary for summary in summaries if summary.id == sender), None)
        sender_parent = origin.parent_session_id if origin is not None else None
        by_id = {summary.id: summary for summary in summaries}
        spawned_descriptions: dict[str, dict[str, str]] = {}
        peers: list[PeerInfo] = []
        for summary in summaries:
            if not reachable(summary, sender, sender_parent, work_dir):
                continue
            description = summary.title or ""
            parent = by_id.get(summary.parent_session_id or "")
            if not description and parent is not None:
                if parent.id not in spawned_descriptions:
                    spawn_rows = await asyncio.to_thread(
                        get_store_for_path(Path(parent.work_dir)).scan_spawned_sub_agents, parent.id
                    )
                    spawned_descriptions[parent.id] = {
                        entry.session_id: entry.sub_agent_desc for _, entry in spawn_rows
                    }
                description = spawned_descriptions[parent.id].get(summary.id, "")
            peers.append(
                PeerInfo(
                    session_id=summary.id,
                    name=summary.name,
                    state=_headless_state(state, headless, summary.id),
                    description=description,
                    work_dir=summary.work_dir,
                )
            )
        return peers

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
