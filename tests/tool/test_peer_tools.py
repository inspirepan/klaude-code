from __future__ import annotations

import asyncio
import builtins
import json
from pathlib import Path

from klaude_code.protocol.peer import PeerInfo, PeerReceipt
from klaude_code.tool.core.context import TodoContext, ToolContext
from klaude_code.tool.peer_tool import ListPeersTool, MessagePeerTool


def test_native_peer_tools_bind_sender_to_context_and_return_only_transport_receipt(tmp_path: Path) -> None:
    async def run() -> None:
        calls: list[tuple[str, str, str, str | None]] = []

        class Port:
            async def list(self, sender: str, work_dir: Path) -> builtins.list[PeerInfo]:
                assert sender == "runtime-session" and work_dir == tmp_path
                return [PeerInfo(session_id="peer", state="running", work_dir=str(tmp_path))]

            async def send(self, sender: str, target: str, body: str, reply_to: str | None = None) -> PeerReceipt:
                calls.append((sender, target, body, reply_to))
                return PeerReceipt(message_id="message", target=target)

        context = ToolContext(
            file_tracker={},
            todo_context=TodoContext(get_todos=lambda: [], set_todos=lambda _items: None),
            session_id="runtime-session",
            work_dir=tmp_path,
            peer_control=Port(),
        )
        discovery = await ListPeersTool.call("{}", context)
        assert discovery.status == "success"
        assert "Session: peer" in discovery.output_text and "Status: running" in discovery.output_text
        result = await MessagePeerTool.call(
            json.dumps(
                {
                    "target": "peer",
                    "body": "body",
                    "reply_to": "previous",
                    "sender_session_id": "forged",
                }
            ),
            context,
        )
        assert result.status == "success"
        assert calls == [("runtime-session", "peer", "body", "previous")]
        assert "Message: message" in result.output_text and "Target: peer" in result.output_text
        assert "Accepted: true" in result.output_text and "Delivery: queued" in result.output_text
        assert "not proof of reading or a reply" in result.output_text

    asyncio.run(run())
