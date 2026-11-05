"""Runtime seam shared by the TUI runner and in-process execution adapter."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass, field
from threading import Event
from typing import Protocol

from klaude_code.protocol import events, op
from klaude_code.protocol.background_task import TaskRequest, TaskResponse
from klaude_code.protocol.model_catalog import ModelCatalog
from klaude_code.protocol.models.session_status import SessionStatus, SessionStatusCategory
from klaude_code.protocol.peer import PeerReceipt


@dataclass
class SessionInfoSnapshot:
    """Snapshot of the locally owned session."""

    session_id: str = ""
    state: SessionStatusCategory = "idle"
    status: SessionStatus = field(default_factory=SessionStatus)
    model_config_name: str | None = None
    #: The model the next request will use, read from the live client. The
    #: prompt bar falls back to ``model_config_name`` when it is absent.
    active_model_name: str | None = None
    provider_name: str | None = None
    effort: str | None = None
    work_dir: str | None = None
    title: str | None = None
    steering: tuple[str, ...] = field(default_factory=tuple)
    is_replay_snapshot: bool = False
    replay_through_event_seq: int = 0


class RuntimeClient(Protocol):
    """Operations, event delivery, and state required by the TUI runner."""

    # -- lifecycle --

    @property
    def session_id(self) -> str: ...

    async def start(self) -> None:
        """Initialize execution and buffer the initial history replay."""
        ...

    async def close(self) -> None: ...

    async def switch_session(self, session_id: str) -> None:
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
        """Echo a user message into the session narrative."""
        ...

    async def emit_local_event(self, event: events.Event) -> None:
        """Inject a display-only event into this client's display feed."""
        ...

    async def dequeue_steering(self) -> tuple[str, ...]: ...

    async def get_model_catalog(self) -> ModelCatalog:
        """Read currently available models from this process configuration."""
        ...

    async def manage_tasks(self, request: TaskRequest) -> TaskResponse:
        """Query/control owned tasks without transcript writes or delivery acknowledgments."""
        ...

    async def send_task_message(self, task_id: str, body: str) -> PeerReceipt:
        """Send untrusted external peer data to one owned child, never root input."""
        ...

    # -- mirrors (synchronous reads for the prompt bar) --

    def is_running(self) -> bool: ...

    def active_operation_id(self) -> str | None: ...

    def steering_texts(self) -> tuple[str, ...]: ...

    def optimistically_append_steering(self, texts: Sequence[str]) -> None:
        """Show newly queued texts in the mirror immediately; the runtime's
        SteeringQueueUpdatedEvent reconciles the authoritative list."""
        ...

    def remove_optimistic_steering(self, text: str) -> None:
        """Roll back one optimistic entry whose runtime submit failed."""
        ...

    def session_info(self) -> SessionInfoSnapshot: ...

    def consume_interrupt_prefill(self) -> str | None: ...

    def state_changed_event(self) -> asyncio.Event:
        """Set whenever running state or the steering queue changes."""
        ...

    # -- interactions --

    def interaction_requests(self) -> asyncio.Queue[events.UserInteractionRequestEvent]: ...

    def interaction_closed_event(self, request: events.UserInteractionRequestEvent) -> Event: ...
