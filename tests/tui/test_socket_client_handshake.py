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


def _error_envelope(message: str) -> events.EventEnvelope:
    return events.EventEnvelope(
        event_id="e1",
        event_seq=1,
        session_id="session-id",
        event_type="error",
        durability="ephemeral",
        timestamp=0.0,
        event=events.ErrorEvent(session_id="session-id", error_message=message, can_retry=False),
    )


def test_stale_server_errors_carry_reload_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:local")
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def run() -> events.EventEnvelope:
        await client._check_server_code({"protocol_version": PROTOCOL_VERSION, "code_fingerprint": "git:old"})
        _ = client._display_queue.get_nowait()  # mismatch notice
        await client._handle_envelope(_error_envelope("Operation failed: Unknown model: gpt-6-luna@codex"))
        return client._display_queue.get_nowait()

    event = asyncio.run(run()).event
    assert isinstance(event, events.ErrorEvent)
    assert event.error_message.startswith("Operation failed: Unknown model")
    assert "klaude server reload --force" in event.error_message


def test_current_server_errors_are_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(update, "get_code_fingerprint", lambda: "git:local")
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)

    async def run() -> events.EventEnvelope:
        await client._check_server_code({"protocol_version": PROTOCOL_VERSION, "code_fingerprint": "git:local"})
        await client._handle_envelope(_error_envelope("boom"))
        return client._display_queue.get_nowait()

    event = asyncio.run(run()).event
    assert isinstance(event, events.ErrorEvent)
    assert event.error_message == "boom"


def test_config_warnings_show_once(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SocketRuntimeClient("session-id", on_envelope=_ignore_envelope)
    frame = {"config_warnings": ["sub_agent_models.finder 'gpt-5.6-luna@codex' is unavailable"]}

    async def run() -> None:
        await client._show_config_warnings(frame)
        await client._show_config_warnings(frame)

    asyncio.run(run())
    notice = client._display_queue.get_nowait().event
    assert isinstance(notice, events.NoticeEvent)
    assert "gpt-5.6-luna@codex" in notice.content
    assert client._display_queue.empty()
