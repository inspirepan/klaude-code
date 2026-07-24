from __future__ import annotations

import asyncio
import contextlib
import json
import os
import time
from pathlib import Path

from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.protocol.models import SessionRuntimeState

_SOURCE = "klaude-code"
_METADATA_SOURCE = "klaude-code:metadata"
_AGENT = "klaude"
_SOCKET_TIMEOUT_SECONDS = 0.5
_RETRY_SECONDS = 1.0
_UNSET = object()


class HerdrReporter:
    """Report Klaude lifecycle state when running in a Herdr pane."""

    def __init__(self, socket_path: Path, pane_id: str) -> None:
        self._socket_path = socket_path
        self._pane_id = pane_id
        self._seq = time.time_ns()
        self._session_states: dict[str, SessionRuntimeState] = {}
        self._desired_state = "idle"
        self._sent_state: str | None = None
        self._title_session_id: str | None = None
        self._desired_title: str | None = None
        self._sent_title: str | None | object = _UNSET
        self._wake = asyncio.Event()
        self._worker = asyncio.create_task(self._send_loop())
        self._closed = False
        self._wake.set()

    @classmethod
    def from_env(cls) -> HerdrReporter | None:
        """Create a reporter from Herdr's managed-pane environment."""
        if os.environ.get("HERDR_ENV") != "1":
            return None
        socket_path = os.environ.get("HERDR_SOCKET_PATH")
        pane_id = os.environ.get("HERDR_PANE_ID")
        if not socket_path or not pane_id:
            return None
        return cls(Path(socket_path), pane_id)

    def report_session_state(self, session_id: str, state: SessionRuntimeState) -> None:
        """Update one session and report the aggregate process state."""
        if self._closed:
            return
        self._session_states[session_id] = state
        desired_state = self._aggregate_state()
        if desired_state != self._desired_state:
            self._desired_state = desired_state
            self._wake.set()

    def consume_event(self, event: events.Event) -> None:
        """Update pane metadata from session title events."""
        if isinstance(event, events.WelcomeEvent):
            self._title_session_id = event.session_id
            self.report_title(event.title)
        elif isinstance(event, events.SessionTitleChangedEvent) and event.session_id == self._title_session_id:
            self.report_title(event.title)

    def report_title(self, title: str | None) -> None:
        """Report the active conversation title as Herdr pane metadata."""
        if self._closed:
            return
        normalized_title = title.strip() if title and title.strip() else None
        if normalized_title != self._desired_title or self._sent_title is _UNSET:
            self._desired_title = normalized_title
            self._wake.set()

    async def close(self) -> None:
        """Flush pending reports and release the pane authority."""
        if self._closed:
            return
        self._closed = True
        self._worker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._worker
        await self._send_best_effort(self._request("pane.release_agent"))

    def _aggregate_state(self) -> str:
        states = self._session_states.values()
        if SessionRuntimeState.WAITING_USER_INPUT in states:
            return "blocked"
        if SessionRuntimeState.RUNNING in states:
            return "working"
        return "idle"

    def _request(self, method: str, *, state: str | None = None) -> dict[str, object]:
        self._seq += 1
        params: dict[str, object] = {
            "pane_id": self._pane_id,
            "source": _SOURCE,
            "agent": _AGENT,
            "seq": self._seq,
        }
        if state is not None:
            params["state"] = state
        return {"id": f"klaude:{method}:{self._seq}", "method": method, "params": params}

    def _metadata_request(self, title: str | None) -> dict[str, object]:
        self._seq += 1
        params: dict[str, object] = {
            "pane_id": self._pane_id,
            "source": _METADATA_SOURCE,
            "agent": _AGENT,
            "applies_to_source": _SOURCE,
            "seq": self._seq,
        }
        if title is None:
            params["clear_title"] = True
            params["clear_display_agent"] = True
        else:
            params["title"] = title
            params["display_agent"] = title
        return {"id": f"klaude:pane.report_metadata:{self._seq}", "method": "pane.report_metadata", "params": params}

    async def _send_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._sent_state != self._desired_state or self._sent_title != self._desired_title:
                failed = False
                if self._sent_state != self._desired_state:
                    state = self._desired_state
                    if await self._send_best_effort(self._request("pane.report_agent", state=state)):
                        self._sent_state = state
                    else:
                        failed = True
                if self._sent_title != self._desired_title:
                    title = self._desired_title
                    if await self._send_best_effort(self._metadata_request(title)):
                        self._sent_title = title
                    else:
                        failed = True
                if not failed:
                    continue
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=_RETRY_SECONDS)
                self._wake.clear()

    async def _send_best_effort(self, request: dict[str, object]) -> bool:
        try:
            async with asyncio.timeout(_SOCKET_TIMEOUT_SECONDS):
                reader, writer = await asyncio.open_unix_connection(self._socket_path)
                try:
                    writer.write(json.dumps(request, separators=(",", ":")).encode() + b"\n")
                    await writer.drain()
                    await reader.readline()
                finally:
                    writer.close()
                    await writer.wait_closed()
        except (OSError, TimeoutError) as exc:
            log_debug(f"Herdr lifecycle report failed: {exc}", debug_type=DebugType.EXECUTION)
            return False
        return True
