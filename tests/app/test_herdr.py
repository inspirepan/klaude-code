import asyncio
import json
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

import klaude_code.app.herdr as herdr_module
from klaude_code.app.herdr import HerdrReporter
from klaude_code.protocol import events
from klaude_code.protocol.models import SessionRuntimeState


def test_reporter_sends_aggregate_lifecycle_and_release() -> None:
    async def _test() -> None:
        socket_path = Path("/tmp") / f"klaude-herdr-{uuid4().hex}.sock"
        requests: list[dict[str, object]] = []

        async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
            data = await reader.readline()
            requests.append(json.loads(data))
            writer.write(b'{"result":{"ok":true}}\n')
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(_handle, path=socket_path)
        try:
            reporter = HerdrReporter(socket_path, "w1:p1")
            await _wait_for_request_count(requests, 2)
            reporter.report_session_state("s1", SessionRuntimeState.RUNNING)
            await _wait_for_request_count(requests, 3)
            reporter.report_session_state("s1", SessionRuntimeState.RUNNING)
            reporter.report_session_state("s2", SessionRuntimeState.WAITING_USER_INPUT)
            await _wait_for_request_count(requests, 4)
            reporter.report_session_state("s2", SessionRuntimeState.IDLE)
            await _wait_for_request_count(requests, 5)
            reporter.report_session_state("s1", SessionRuntimeState.IDLE)
            await _wait_for_request_count(requests, 6)
            await reporter.close()
        finally:
            server.close()
            await server.wait_closed()
            socket_path.unlink(missing_ok=True)

        assert [request["method"] for request in requests] == [
            "pane.report_agent",
            "pane.report_metadata",
            "pane.report_agent",
            "pane.report_agent",
            "pane.report_agent",
            "pane.report_agent",
            "pane.release_agent",
        ]
        params = [cast(dict[str, object], request["params"]) for request in requests]
        lifecycle_params = [
            cast(dict[str, object], request["params"])
            for request in requests
            if request["method"] == "pane.report_agent"
        ]
        assert [param["state"] for param in lifecycle_params] == ["idle", "working", "blocked", "working", "idle"]
        assert all(param["pane_id"] == "w1:p1" for param in params)
        assert {param["source"] for param in params} == {"klaude-code", "klaude-code:metadata"}
        assert all(param["agent"] == "klaude" for param in params)
        sequences = [cast(int, param["seq"]) for param in params]
        assert sequences == sorted(sequences)
        assert len(sequences) == len(set(sequences))

    asyncio.run(_test())


def test_reporter_from_env_requires_complete_herdr_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HERDR_ENV", "1")
    monkeypatch.delenv("HERDR_SOCKET_PATH", raising=False)
    monkeypatch.delenv("HERDR_PANE_ID", raising=False)

    assert HerdrReporter.from_env() is None


def test_reporter_retries_unsent_latest_state(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _test() -> None:
        requests: list[dict[str, object]] = []
        state_attempts = 0

        async def _send(request: dict[str, object]) -> bool:
            nonlocal state_attempts
            requests.append(request)
            if request["method"] != "pane.report_agent":
                return True
            state_attempts += 1
            return state_attempts > 1

        monkeypatch.setattr(herdr_module, "_RETRY_SECONDS", 0.001)
        reporter = HerdrReporter(Path("/unused"), "w1:p1")
        monkeypatch.setattr(reporter, "_send_best_effort", _send)

        async with asyncio.timeout(1):
            while state_attempts < 2:
                await asyncio.sleep(0.001)
        await reporter.close()

        params = [
            cast(dict[str, object], request["params"])
            for request in requests
            if request["method"] == "pane.report_agent"
        ]
        assert [param["state"] for param in params] == ["idle", "idle"]
        assert requests[-1]["method"] == "pane.release_agent"

    asyncio.run(_test())


def test_reporter_sends_and_clears_conversation_title(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _test() -> None:
        requests: list[dict[str, object]] = []

        async def _send(request: dict[str, object]) -> bool:
            requests.append(request)
            return True

        reporter = HerdrReporter(Path("/unused"), "w1:p1")
        monkeypatch.setattr(reporter, "_send_best_effort", _send)

        await _wait_for_request_count(requests, 2)
        reporter.consume_event(events.WelcomeEvent.model_construct(session_id="s1", title=" Refactor authentication "))
        await _wait_for_request_count(requests, 3)
        reporter.consume_event(events.SessionTitleChangedEvent(session_id="s2", title="Ignored background title"))
        reporter.consume_event(events.SessionTitleChangedEvent(session_id="s1", title=""))
        await _wait_for_request_count(requests, 4)
        await reporter.close()

        metadata = [request for request in requests if request["method"] == "pane.report_metadata"]
        params = [cast(dict[str, object], request["params"]) for request in metadata]
        assert params == [
            {
                "pane_id": "w1:p1",
                "source": "klaude-code:metadata",
                "agent": "klaude",
                "applies_to_source": "klaude-code",
                "seq": params[0]["seq"],
                "clear_title": True,
                "clear_display_agent": True,
            },
            {
                "pane_id": "w1:p1",
                "source": "klaude-code:metadata",
                "agent": "klaude",
                "applies_to_source": "klaude-code",
                "seq": params[1]["seq"],
                "title": "Refactor authentication",
                "display_agent": "Refactor authentication",
            },
            {
                "pane_id": "w1:p1",
                "source": "klaude-code:metadata",
                "agent": "klaude",
                "applies_to_source": "klaude-code",
                "seq": params[2]["seq"],
                "clear_title": True,
                "clear_display_agent": True,
            },
        ]

    asyncio.run(_test())


async def _wait_for_request_count(requests: list[dict[str, object]], count: int) -> None:
    async with asyncio.timeout(1):
        while len(requests) < count:
            await asyncio.sleep(0.001)
