from __future__ import annotations

import asyncio
import base64
import contextlib
import sys
from typing import TextIO

from klaude_code.log import DebugType, log_debug
from klaude_code.protocol import events
from klaude_code.protocol.models.session_status import SessionStatus
from klaude_code.protocol.user_interaction import AskUserQuestionRequestPayload
from klaude_code.tui.terminal.title import set_native_status_supported
from klaude_code.tui.terminal.tty_state import scrollback_write_in_flight, stdout_writable

_RETRY_SECONDS = 0.08
_CLOSE_TIMEOUT_SECONDS = 0.5
_STANDARD_STATES = {"idle", "working", "done", "blocked", "error"}


class ProgramStatusReporter:
    """Report aggregate TUI state using OSC 7501 root records."""

    def __init__(self, stream: TextIO) -> None:
        self._stream = stream
        self._session_states: dict[str, SessionStatus] = {}
        self._turn_ids: dict[str, str | None] = {}
        self._results: dict[str, str] = {}
        self._requests: dict[tuple[str, str], events.UserInteractionRequestEvent] = {}
        self._desired_state = "state=idle:app=klaude"
        self._sent_state: str | None = None
        self._states: set[str] | None = None
        self._kinds: set[str] = {"question", "permission", "auth"}
        self._probe_requested = False
        self._probe_sent = False
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

    def start_detection(self) -> None:
        """Query only once prompt-toolkit has installed its input parser."""
        if not self._closed and not self._probe_requested:
            self._probe_requested = True
            self._wake.set()

    def receive_capabilities(self, reply: str) -> None:
        if self._closed or not self._probe_sent:
            return
        body = reply.removeprefix("\x1b]7501;").removesuffix("\x07").removesuffix("\x1b\\")
        fields = body.split(":")
        if fields[0].strip() != "?":
            return
        capabilities = dict(field.strip().split("=", 1) for field in fields[1:] if "=" in field)
        capabilities = {key.strip(): value.strip() for key, value in capabilities.items()}
        self._states = (
            {value.strip() for value in capabilities["states"].split(",")}
            if "states" in capabilities
            else _STANDARD_STATES.copy()
        )
        self._kinds = (
            {value.strip() for value in capabilities["kinds"].split(",")}
            if "kinds" in capabilities
            else {"question", "permission", "auth"}
        )
        set_native_status_supported(self._states >= _STANDARD_STATES)
        self._refresh()

    def report_session_state(self, session_id: str, state: SessionStatus, *, snapshot: bool = False) -> None:
        if self._closed:
            return
        if snapshot:
            self._session_states.clear()
            self._turn_ids.clear()
            self._results.clear()
            pending = {(item.source_session_id, item.request_id) for item in state.attention}
            self._requests = {key: request for key, request in self._requests.items() if key in pending}
        turn = state.last_turn
        turn_id = turn.id if turn is not None else None
        if snapshot or session_id not in self._turn_ids:
            self._turn_ids[session_id] = turn_id
            self._results.pop(session_id, None)
        elif turn is not None and turn_id != self._turn_ids[session_id]:
            self._turn_ids[session_id] = turn_id
            self._results[session_id] = {"succeeded": "done", "failed": "error", "interrupted": "idle"}[turn.result]
        previous = self._session_states.get(session_id)
        if any(item.kind == "needs_input" for item in state.attention) or (
            state.execution != "none"
            and (previous is None or previous.execution == "none")
            and turn_id == (previous.last_turn.id if previous is not None and previous.last_turn is not None else None)
        ):
            self._results.pop(session_id, None)
        self._session_states[session_id] = state
        self._refresh()

    def report_interaction(self, event: events.Event) -> None:
        if self._closed:
            return
        if isinstance(event, events.UserInteractionRequestEvent):
            self._requests[event.session_id, event.request_id] = event
        elif isinstance(event, events.UserInteractionResolvedEvent | events.UserInteractionCancelledEvent):
            self._requests.pop((event.session_id, event.request_id), None)
        else:
            return
        self._refresh()

    def _refresh(self) -> None:
        states = list(self._session_states.values())
        attention = [item for state in states for item in state.attention]
        errors = [item for item in attention if item.kind == "error"]
        blocked = [item for item in attention if item.kind != "error"]
        kind = None
        msg = None
        if errors:
            desired_state = "error"
            msg = errors[0].message
        elif blocked or any(state.category == "needs_you" for state in states):
            desired_state = "blocked"
            msg = "Input required"
            if blocked:
                item = blocked[0]
                request = self._requests.get((item.source_session_id, item.request_id or ""))
                msg = item.message
                if item.kind == "needs_input":
                    if request is not None:
                        kind = "permission" if request.source == "approval" else "question"
                        if isinstance(request.payload, AskUserQuestionRequestPayload):
                            msg = " ".join(question.question for question in request.payload.questions)
                        else:
                            msg = request.payload.question
                    elif item.code == "approval":
                        kind, msg = "permission", msg or "Permission required"
                msg = msg or ("Session paused" if item.kind == "paused" else "Input required")
        elif any(
            state.category == "working"
            or state.execution != "none"
            or state.owned.active_agents
            or state.owned.active_shells
            for state in states
        ):
            desired_state = "working"
        else:
            results = self._results.values()
            desired_state = "error" if "error" in results else "done" if "done" in results else "idle"
        if self._states is not None and desired_state not in self._states:
            return
        record = f"state={desired_state}:app=klaude"
        if kind is not None and kind in self._kinds:
            record += f":kind={kind}"
        if msg:
            # Terminal records must be single-line, control-free, and bounded.
            msg = " ".join("".join(c if c.isprintable() else " " for c in msg).split())
            msg = msg.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
            record += ":msg=" + base64.b64encode(msg.encode("utf-8")).decode("ascii")
        desired_state = record
        if desired_state != self._desired_state:
            self._desired_state = desired_state
            self._wake.set()

    async def close(self) -> None:
        """Clear terminal records, with bounded retries while the TTY is busy."""
        if self._closed:
            return
        self._closed = True
        set_native_status_supported(False)
        self._desired_state = "state=clear"
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
            while self._sent_state != self._desired_state or (
                self._probe_requested and not self._probe_sent and not self._closed
            ):
                if self._probe_requested and not self._probe_sent and not self._closed:
                    if self._try_write("?"):
                        self._probe_sent = True
                        continue
                else:
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
        try:
            self._stream.write(f"\x1b]7501;{state}\x1b\\")
            self._stream.flush()
        except Exception as exc:
            log_debug(f"Program status write failed: {exc}", debug_type=DebugType.TERMINAL)
            return False
        return True
