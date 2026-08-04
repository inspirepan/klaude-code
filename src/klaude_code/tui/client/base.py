"""Client-side interface between the TUI runner and the klaude server.

The TUI no longer embeds a runtime: it attaches to the single local server
and speaks the WS frame protocol. ``RuntimeClient`` is the seam — the runner
only depends on this protocol, so tests can inject an in-memory fake, and the
sole production implementation is :class:`SocketRuntimeClient` (UDS WebSocket).
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from klaude_code.protocol import events, op


class ClientConnectionError(Exception):
    """Send-side operation failed because the server connection is gone.

    The receive loop surfaces its own error event when the socket drops;
    this lets the input loop distinguish a dead connection from a bug and
    detach gracefully instead of crashing with a traceback.
    """


@dataclass
class SessionInfoSnapshot:
    """Client-side mirror of the server's session_info frame."""

    session_id: str = ""
    state: str = "idle"
    model_config_name: str | None = None
    provider_name: str | None = None
    effort: str | None = None
    work_dir: str | None = None
    title: str | None = None
    follow_ups: tuple[str, ...] = field(default_factory=tuple)


class RuntimeClient(Protocol):
    """What the TUI runner needs from the server connection."""

    # -- lifecycle --

    @property
    def session_id(self) -> str: ...

    async def start(self) -> None:
        """Connect and complete the attach handshake (replay buffered)."""
        ...

    async def close(self) -> None: ...

    async def reattach(self, session_id: str) -> None:
        """Switch this client to another session (/new, /fork-session)."""
        ...

    # -- display feed --

    def start_display(self) -> None:
        """Begin delivering buffered + live envelopes to the display."""
        ...

    async def wait_for_display_idle(self) -> None: ...

    async def wait_for_replay_complete(self) -> None: ...

    # -- operations & events --

    async def submit(self, operation: op.Operation) -> str: ...

    async def wait_for(self, operation_id: str) -> None: ...

    async def submit_and_wait(self, operation: op.Operation) -> None: ...

    async def emit_user_message(self, event: events.UserMessageEvent) -> None:
        """Echo a user message into the shared session narrative (all clients)."""
        ...

    async def emit_local_event(self, event: events.Event) -> None:
        """Inject a display-only event into this client's display feed."""
        ...

    async def dequeue_follow_ups(self) -> tuple[str, ...]: ...

    # -- mirrors (synchronous reads for the prompt bar) --

    def is_running(self) -> bool: ...

    def follow_up_texts(self) -> tuple[str, ...]: ...

    def optimistically_append_follow_ups(self, texts: Sequence[str]) -> None:
        """Show newly queued texts in the mirror immediately; the server's
        FollowUpQueueUpdatedEvent reconciles the authoritative list."""
        ...

    def session_info(self) -> SessionInfoSnapshot: ...

    def consume_interrupt_prefill(self) -> str | None: ...

    def state_changed_event(self) -> asyncio.Event:
        """Set whenever running state or the follow-up queue changes."""
        ...

    # -- interactions --

    def interaction_requests(self) -> asyncio.Queue[events.UserInteractionRequestEvent]: ...
