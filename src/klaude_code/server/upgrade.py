"""Server-owned upgrade and reload scheduling.

The server is the long-lived process, so it installs new code and re-execs
itself. Both happen only at an idle boundary: no running turn, no pending
interaction, no queued follow-up. Installing while a turn runs would leave the
process on a half-replaced venv (already-imported old modules plus lazily
imported new ones), so a busy server keeps the request pending and retries at
every idle edge instead of racing clients that poll ``/status``.

Clients only register intent (``request``) and read ``status``; they never
decide when the switch happens.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from klaude_code.control.event_bus import EventBus
from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.server.lifecycle import ServerLifecycle
from klaude_code.update import AutoUpgradeResult

UpgradeAction = Literal["upgrade", "reload"]
UpgradePhase = Literal["idle", "pending", "installing", "reloading", "failed"]

# Re-check for an idle boundary this often while an action is pending. Turn
# ends nudge the loop directly; the poll covers transitions that publish no
# event (interaction responses, headless queue edits).
POLL_INTERVAL_SECONDS = 2.0
# After closing the admission gate, let callbacks that were already scheduled
# (a follow-up drain right behind a TaskFinishEvent) land before trusting the
# idle reading.
SETTLE_SECONDS = 0.1

ActiveSessionsProvider = Callable[[], list[dict[str, str]]]
Installer = Callable[[bool], AutoUpgradeResult]
FingerprintResolver = Callable[[AutoUpgradeResult], str | None]
Notifier = Callable[[str, bool], Awaitable[None]]


class UpgradeCoordinator:
    """Holds one pending action and runs it at the next idle boundary.

    ``upgrade`` installs the latest code and then reloads; ``reload`` only
    re-execs on the code already on disk. An upgrade request supersedes a
    pending reload; repeated requests are idempotent.
    """

    def __init__(
        self,
        *,
        lifecycle: ServerLifecycle,
        active_sessions: ActiveSessionsProvider,
        installer: Installer,
        target_fingerprint: FingerprintResolver,
        notify: Notifier | None = None,
        poll_interval: float = POLL_INTERVAL_SECONDS,
        settle_seconds: float = SETTLE_SECONDS,
    ) -> None:
        self._lifecycle = lifecycle
        self._active_sessions = active_sessions
        self._installer = installer
        self._target_fingerprint = target_fingerprint
        self._notify = notify
        self._poll_interval = poll_interval
        self._settle_seconds = settle_seconds
        self.phase: UpgradePhase = "idle"
        self.action: UpgradeAction | None = None
        self.check_first = False
        self.requested_at: float | None = None
        self.message: str | None = None
        self.target_fingerprint: str | None = None
        self._gate_closed = False
        self._nudge = asyncio.Event()
        self._loop_task: asyncio.Task[None] | None = None
        self._watch_task: asyncio.Task[None] | None = None

    # -- client-facing --

    def request(self, action: UpgradeAction, *, check: bool = False) -> dict[str, Any]:
        """Register an action; returns the status after registration."""

        if self.phase in ("installing", "reloading"):
            return self.status()
        if action == "upgrade" or self.action is None:
            self.action = action
        self.check_first = self.check_first or check
        self.phase = "pending"
        self.requested_at = time.time()
        self.message = None
        self.target_fingerprint = None
        self._nudge.set()
        self._ensure_loop()
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "action": self.action,
            "requested_at": self.requested_at,
            "message": self.message,
            "target_fingerprint": self.target_fingerprint,
            "active_sessions": self._active_sessions() if self.phase == "pending" else [],
        }

    def admission_error(self) -> str | None:
        """Why a new turn cannot start right now, or None when turns may start."""

        if not self._gate_closed:
            return None
        if self.phase == "installing":
            return "klaude server is installing an update and restarts when done; retry in a moment"
        return "klaude server is restarting; retry in a moment"

    def nudge(self) -> None:
        """Signal a possible idle edge (a turn finished, a queue drained)."""

        self._nudge.set()

    def start(self, event_bus: EventBus) -> None:
        """Nudge the scheduler on turn boundaries so idle edges fire promptly."""

        if self._watch_task is None:
            self._watch_task = asyncio.get_running_loop().create_task(self._watch(event_bus))

    async def aclose(self) -> None:
        tasks = [task for task in (self._loop_task, self._watch_task) if task is not None]
        self._loop_task = None
        self._watch_task = None
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _watch(self, event_bus: EventBus) -> None:
        subscription = event_bus.subscribe(None)
        while True:
            async for envelope in subscription:
                event = envelope.event
                if isinstance(event, events.EndEvent):
                    return
                if isinstance(
                    event,
                    events.TaskFinishEvent
                    | events.OperationFinishedEvent
                    | events.FollowUpQueueUpdatedEvent
                    | events.InterruptEvent,
                ):
                    self._nudge.set()
            # Bus dropped this subscriber on overflow; resubscribe.
            subscription = event_bus.subscribe(None)

    # -- scheduling --

    def _ensure_loop(self) -> None:
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.get_running_loop().create_task(self._run())

    async def _run(self) -> None:
        while self.phase == "pending":
            self._nudge.clear()
            await self._try_fire()
            if self.phase != "pending":
                break
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._nudge.wait(), self._poll_interval)

    async def _try_fire(self) -> None:
        if self._active_sessions():
            return
        # Close admission first, then re-read: a turn accepted between the
        # reading and the gate would otherwise run on a replaced venv.
        self._gate_closed = True
        await asyncio.sleep(self._settle_seconds)
        if self._active_sessions():
            self._gate_closed = False
            return
        if self.action == "reload":
            self.phase = "reloading"
            self.message = "reloading on the installed code"
            log_debug("[upgrade] idle boundary reached; reloading", debug_type=DebugType.EXECUTION)
            self._lifecycle.request_reload()
            return
        await self._install_and_reload()

    async def _install_and_reload(self) -> None:
        self.phase = "installing"
        log_debug(
            f"[upgrade] idle boundary reached; installing (check={self.check_first})", debug_type=DebugType.EXECUTION
        )
        await self._say("klaude server is installing an update; new turns are paused until it restarts.", False)
        check = self.check_first
        try:
            result = await asyncio.to_thread(self._installer, check)
        except Exception as exc:
            result = AutoUpgradeResult(False, None, f"upgrade failed: {exc}", "warn")
        if result.performed:
            self.target_fingerprint = self._target_fingerprint(result)
            self.phase = "reloading"
            self.message = result.message or "update installed; reloading"
            log_debug(f"[upgrade] installed {self.target_fingerprint}; reloading", debug_type=DebugType.EXECUTION)
            self._lifecycle.request_reload()
            return
        self._gate_closed = False
        self.action = None
        self.check_first = False
        if result.message is None:
            self.phase = "idle"
            self.message = "already up to date"
            await self._say("klaude server is already on the latest code; no restart needed.", False)
            return
        self.phase = "failed"
        self.message = result.message
        log_debug(f"[upgrade] install failed: {result.message}", debug_type=DebugType.EXECUTION)
        await self._say(f"klaude upgrade failed: {result.message}", True)

    async def _say(self, text: str, is_error: bool) -> None:
        if self._notify is None:
            return
        try:
            await self._notify(text, is_error)
        except Exception as exc:
            log_debug(f"[upgrade] notify failed: {exc}", debug_type=DebugType.EXECUTION)
