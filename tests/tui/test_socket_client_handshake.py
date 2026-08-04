from __future__ import annotations

import asyncio

import pytest

from klaude_code import update
from klaude_code.protocol import events
from klaude_code.protocol.version import PROTOCOL_VERSION
from klaude_code.tui.client.socket_client import SocketRuntimeClient


async def _ignore_envelope(_envelope: events.EventEnvelope) -> None:
    return


def test_protocol_mismatch_emits_explicit_error_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:local")
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def check() -> events.NoticeEvent:
        await client._check_server_code(
            {
                "protocol_version": PROTOCOL_VERSION + 1,
                "code_fingerprint": "git:local",
            }
        )
        envelope = client._display_queue.get_nowait()
        assert isinstance(envelope.event, events.NoticeEvent)
        return envelope.event

    notice = asyncio.run(check())
    assert notice.is_error is True
    assert "compatibility mismatch" in notice.content
    assert "protocol server=" in notice.content


def test_matching_protocol_and_code_emit_no_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:local")
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    asyncio.run(
        client._check_server_code(
            {
                "protocol_version": PROTOCOL_VERSION,
                "code_fingerprint": "git:local",
            }
        )
    )
    assert client._display_queue.empty()
