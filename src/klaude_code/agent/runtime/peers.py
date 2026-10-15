"""Narrow callback bridge; discovery and scheduling stay server-owned."""

from collections.abc import Awaitable, Callable
from pathlib import Path

from klaude_code.protocol.peer import PeerInfo, PeerReceipt

type ListPeers = Callable[[str, Path], Awaitable[list[PeerInfo]]]
type MessagePeer = Callable[[str, str, str, str | None], Awaitable[PeerReceipt]]


class PeerControl:
    def __init__(self) -> None:
        self.list_callback: ListPeers | None = None
        self.send_callback: MessagePeer | None = None

    async def list(self, sender: str, work_dir: Path) -> list[PeerInfo]:
        if self.list_callback is None:
            raise ValueError("Peer discovery is unavailable")
        return await self.list_callback(sender, work_dir)

    async def send(self, sender: str, target: str, body: str, reply_to: str | None = None) -> PeerReceipt:
        if self.send_callback is None:
            raise ValueError("Peer messaging is unavailable")
        return await self.send_callback(sender, target, body, reply_to)
