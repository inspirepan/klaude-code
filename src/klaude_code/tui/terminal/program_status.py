from __future__ import annotations

import asyncio
import contextlib
import sys
from typing import TextIO

from klaude_code.log import DebugType, log_debug
from klaude_code.protocol.models.session_status import SessionStatusCategory
from klaude_code.tui.terminal.tty_state import scrollback_write_in_flight, stdout_writable

_RETRY_SECONDS = 0.08
_CLOSE_TIMEOUT_SECONDS = 0.5


class ProgramStatusReporter:
    """Report aggregate TUI state using OSC 7501 root records."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._session_states: dict[str, SessionStatusCategory] = {}
        self._desired_state = "idle"
        self._sent_state: str | None = None
        self._closed = False
        self._wake = asyncio.Event()
        self._worker = asyncio.create_task(self._send_loop())
        self._wake.set()

    @classmethod
    def from_terminal(cls) -> ProgramStatusReporter | None:
        stream = getattr(sys, "__stdout__", None) or sys.stdout
        try:
            if not stream.isatty():
                return None
        except Exception as exc:
            log_debug(f"Program status TTY probe failed: {exc}", debug_type=DebugType.TERMINAL)
            return None
        return cls(stream)

    def report_session_state(self, session_id: str, state: SessionStatusCategory) -> None:
        if self._closed:
            return
        self._session_states[session_id] = state
        states = self._session_states.values()
        desired_state = "blocked" if "needs_you" in states else "working" if "working" in states else "idle"
        if desired_state != self._desired_state:
            self._desired_state = desired_state
            self._wake.set()

    async def close(self) -> None:
        """Clear terminal records, with bounded retries while the TTY is busy."""
        if self._closed:
            return
        self._closed = True
        self._desired_state = "clear"
        self._wake.set()
        try:
            await asyncio.wait_for(self._worker, timeout=_CLOSE_TIMEOUT_SECONDS)
        except TimeoutError:
            log_debug("Program status clear timed out", debug_type=DebugType.TERMINAL)
        finally:
            self._worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._worker

    async def _send_loop(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._sent_state != self._desired_state:
                state = self._desired_state
                if self._try_write(state):
                    self._sent_state = state
                    continue
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._wake.wait(), timeout=_RETRY_SECONDS)
                self._wake.clear()
            if self._closed:
                return

    def _try_write(self, state: str) -> bool:
        if not stdout_writable() or scrollback_write_in_flight():
            return False
        payload = "state=clear" if state == "clear" else f"state={state}:app=klaude"
        try:
            self._stream.write(f"\x1b]7501;{payload}\x1b\\")
            self._stream.flush()
        except Exception as exc:
            log_debug(f"Program status write failed: {exc}", debug_type=DebugType.TERMINAL)
            return False
        return True
