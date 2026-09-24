# pyright: reportPrivateUsage=false
from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any, cast

from klaude_code.protocol import message
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.server.upgrade import UpgradeCoordinator
from klaude_code.update import AutoUpgradeResult

from .conftest import AppEnv, arun, consume_ws_handshake, receive_events, send_user_message, usage


class _Harness:
    def __init__(self, *, install_result: AutoUpgradeResult | None = None) -> None:
        self.active: list[dict[str, str]] = []
        self.installs: list[bool] = []
        self.notices: list[tuple[str, bool]] = []
        self.exit_calls: list[bool] = []
        self.install_result = install_result or AutoUpgradeResult(True, "2.0.0", "installed", revision="abcd1234")
        self.lifecycle = ServerLifecycle(socket_path=Path("/tmp/unused.sock"))
        self.lifecycle.bind_exit_trigger(lambda: self.exit_calls.append(True))
        self.coordinator = UpgradeCoordinator(
            lifecycle=self.lifecycle,
            active_sessions=lambda: list(self.active),
            installer=self._install,
            target_fingerprint=lambda result: f"pkg:{result.new_version}",
            notify=self._notify,
            poll_interval=0.02,
            settle_seconds=0.0,
        )

    def _install(self, check: bool) -> AutoUpgradeResult:
        self.installs.append(check)
        # The gate must be closed for the whole install.
        assert self.coordinator.admission_error() is not None
        return self.install_result

    async def _notify(self, text: str, is_error: bool) -> None:
        self.notices.append((text, is_error))

    async def wait_phase(self, *phases: str, timeout: float = 2.0) -> None:
        deadline = time.monotonic() + timeout
        while self.coordinator.phase not in phases:
            assert time.monotonic() < deadline, f"phase stuck at {self.coordinator.phase}"
            await asyncio.sleep(0.01)


def test_upgrade_waits_for_idle_then_installs_and_reloads() -> None:
    async def scenario() -> None:
        h = _Harness()
        h.active = [{"session_id": "s1", "state": "running"}]
        status = h.coordinator.request("upgrade")
        assert status["phase"] == "pending"
        assert status["active_sessions"] == h.active
        await asyncio.sleep(0.1)
        assert h.installs == []
        assert h.coordinator.admission_error() is None
        assert h.exit_calls == []

        h.active = []
        h.coordinator.nudge()
        await h.wait_phase("reloading")
        assert h.installs == [False]
        assert h.lifecycle.reload_requested is True
        assert h.exit_calls == [True]
        assert h.coordinator.target_fingerprint == "pkg:2.0.0"
        assert h.coordinator.admission_error() is not None
        assert any("installing an update" in text for text, _ in h.notices)
        await h.coordinator.aclose()

    arun(scenario())


def test_gate_reopens_when_a_turn_slips_in_before_settle() -> None:
    async def scenario() -> None:
        h = _Harness()
        h.coordinator._settle_seconds = 0.05

        async def slip_in() -> None:
            # Wait until the gate closes, then become busy before the re-read.
            while h.coordinator.admission_error() is None:
                await asyncio.sleep(0.001)
            h.active = [{"session_id": "late", "state": "running"}]

        slipper = asyncio.create_task(slip_in())
        h.coordinator.request("upgrade")
        await slipper
        await asyncio.sleep(0.1)
        assert h.installs == []
        assert h.coordinator.phase == "pending"
        assert h.coordinator.admission_error() is None
        h.active = []
        await h.wait_phase("reloading")
        assert h.installs == [False]
        await h.coordinator.aclose()

    arun(scenario())


def test_install_failure_reopens_gate_and_reports() -> None:
    async def scenario() -> None:
        h = _Harness(install_result=AutoUpgradeResult(False, None, "uv reinstall failed (exit 1)", "warn"))
        h.coordinator.request("upgrade")
        await h.wait_phase("failed")
        assert h.exit_calls == []
        assert h.coordinator.admission_error() is None
        assert h.coordinator.action is None
        assert h.coordinator.status()["message"] == "uv reinstall failed (exit 1)"
        assert ("klaude upgrade failed: uv reinstall failed (exit 1)", True) in h.notices
        await h.coordinator.aclose()

    arun(scenario())


def test_nothing_to_install_returns_to_idle_without_reload() -> None:
    async def scenario() -> None:
        h = _Harness(install_result=AutoUpgradeResult(False, None, None))
        h.coordinator.request("upgrade", check=True)
        await h.wait_phase("idle")
        assert h.installs == [True]
        assert h.exit_calls == []
        assert h.coordinator.status()["message"] == "already up to date"
        await h.coordinator.aclose()

    arun(scenario())


def test_reload_action_reexecs_without_installing() -> None:
    async def scenario() -> None:
        h = _Harness()
        h.coordinator.request("reload")
        await h.wait_phase("reloading")
        assert h.installs == []
        assert h.exit_calls == [True]
        await h.coordinator.aclose()

    arun(scenario())


def test_upgrade_supersedes_pending_reload_and_requests_are_idempotent() -> None:
    async def scenario() -> None:
        h = _Harness()
        h.active = [{"session_id": "s1", "state": "waiting_input"}]
        assert h.coordinator.request("reload")["action"] == "reload"
        assert h.coordinator.request("upgrade")["action"] == "upgrade"
        assert h.coordinator.request("reload")["action"] == "upgrade"
        assert h.coordinator.request("upgrade", check=True)["action"] == "upgrade"
        assert h.coordinator.check_first is True
        h.active = []
        await h.wait_phase("reloading")
        assert h.installs == [True]
        assert h.exit_calls == [True]
        await h.coordinator.aclose()

    arun(scenario())


def test_requests_during_install_do_not_restart_the_loop() -> None:
    async def scenario() -> None:
        h = _Harness()
        started = asyncio.Event()
        release = asyncio.Event()
        loop = asyncio.get_running_loop()

        def slow_install(check: bool) -> AutoUpgradeResult:
            del check
            loop.call_soon_threadsafe(started.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(timeout=2)
            return AutoUpgradeResult(True, "2.0.0", "installed")

        h.coordinator._installer = slow_install
        h.coordinator.request("upgrade")
        await asyncio.wait_for(started.wait(), 2)
        assert h.coordinator.request("upgrade")["phase"] == "installing"
        assert "installing an update" in (h.coordinator.admission_error() or "")
        release.set()
        await h.wait_phase("reloading")
        assert h.exit_calls == [True]
        await h.coordinator.aclose()

    arun(scenario())


# -- through the HTTP/WS surface --------------------------------------------


def _coordinator(app_env: AppEnv) -> UpgradeCoordinator:
    coordinator = cast(Any, app_env.client.app).state.server_state.upgrade
    assert isinstance(coordinator, UpgradeCoordinator)
    return coordinator


def _poll_upgrade(app_env: AppEnv, *phases: str, timeout: float = 5.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while True:
        body = app_env.client.get("/api/server/upgrade").json()
        if body["phase"] in phases:
            return body
        assert time.monotonic() < deadline, f"upgrade phase stuck at {body}"
        time.sleep(0.02)


def test_upgrade_endpoint_defers_install_until_the_running_turn_ends(app_env: AppEnv) -> None:
    coordinator = _coordinator(app_env)
    installs: list[bool] = []

    def fake_install(check: bool) -> AutoUpgradeResult:
        installs.append(check)
        return AutoUpgradeResult(True, "9.9.9", "installed")

    coordinator._installer = fake_install
    coordinator._target_fingerprint = lambda result: f"pkg:{result.new_version}"
    coordinator._poll_interval = 0.05
    coordinator._settle_seconds = 0.0

    app_env.fake_llm.enqueue(
        message.AssistantTextDelta(content="slow"),
        message.AssistantMessage(parts=[message.TextPart(text="slow")], stop_reason="stop", usage=usage()),
        delay_s=0.3,
    )
    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "go")
        # The turn is running: registering keeps the upgrade pending.
        body = app_env.client.post("/api/server/upgrade", json={"check": False}).json()
        assert body["phase"] == "pending"
        assert body["active_sessions"] and body["active_sessions"][0]["session_id"] == session_id
        assert installs == []
        assert app_env.exit_calls == []

        finished = _poll_upgrade(app_env, "reloading")
        assert installs == [False]
        assert finished["target_fingerprint"] == "pkg:9.9.9"
        assert app_env.exit_calls == [True]
        assert app_env.lifecycle.reload_requested is True
        # Drain the websocket so the turn's events do not leak into teardown.
        for _ in range(50):
            if any(event.get("event_type") == "operation.finished" for event in receive_events(websocket)):
                break


def test_reload_when_idle_registers_instead_of_refusing(app_env: AppEnv) -> None:
    coordinator = _coordinator(app_env)
    coordinator._poll_interval = 0.05
    coordinator._settle_seconds = 0.0
    app_env.fake_llm.enqueue(
        message.AssistantMessage(parts=[message.TextPart(text="ok")], stop_reason="stop", usage=usage()),
        delay_s=0.3,
    )
    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "go")
        response = app_env.client.post("/api/server/reload", json={"force": False, "when": "idle"})
        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "pending"
        assert body["sessions"] and body["upgrade"]["action"] == "reload"
        assert app_env.exit_calls == []
        _poll_upgrade(app_env, "reloading")
        assert app_env.exit_calls == [True]
        for _ in range(50):
            if any(event.get("event_type") == "operation.finished" for event in receive_events(websocket)):
                break


def test_status_reports_pending_upgrade(app_env: AppEnv) -> None:
    coordinator = _coordinator(app_env)
    coordinator.phase = "pending"
    coordinator.action = "upgrade"
    body = app_env.client.get("/api/server/status").json()
    assert body["upgrade"]["phase"] == "pending"
    assert body["upgrade"]["action"] == "upgrade"


def test_ws_turn_is_rejected_while_the_gate_is_closed(app_env: AppEnv) -> None:
    coordinator = _coordinator(app_env)
    coordinator.phase = "installing"
    coordinator._gate_closed = True
    session_id = app_env.create_session()
    with app_env.client.websocket_connect(f"/api/sessions/{session_id}/ws") as websocket:
        consume_ws_handshake(websocket)
        send_user_message(websocket, session_id, "hi")
        frames: list[dict[str, Any]] = []
        for _ in range(20):
            frames.extend(receive_events(websocket))
            if any(frame.get("event_type") == "operation.finished" for frame in frames):
                break
    error = next(frame for frame in frames if frame.get("type") == "error")
    assert error["code"] == "server_upgrading"
    finished = next(frame for frame in frames if frame.get("event_type") == "operation.finished")
    assert finished["event"]["status"] == "rejected"
    assert app_env.fake_llm.call_count == 0
    coordinator._gate_closed = False
    coordinator.phase = "idle"


def test_headless_run_is_refused_while_the_gate_is_closed(app_env: AppEnv) -> None:
    coordinator = _coordinator(app_env)
    coordinator.phase = "reloading"
    coordinator._gate_closed = True
    response = app_env.client.post("/api/headless/run", json={"prompt": "hi", "work_dir": str(app_env.work_dir)})
    assert response.status_code == 503
    assert "restarting" in response.json()["detail"]
    coordinator._gate_closed = False
    coordinator.phase = "idle"
