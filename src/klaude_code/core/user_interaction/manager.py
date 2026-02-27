from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from klaude_code.protocol import events, user_interaction


@dataclass(frozen=True)
class PendingUserInteractionRequest:
    request_id: str
    session_id: str
    source: user_interaction.UserInteractionSource
    tool_call_id: str | None
    payload: user_interaction.UserInteractionRequestPayload


@dataclass
class _PendingRequestState:
    request: PendingUserInteractionRequest
    future: asyncio.Future[user_interaction.UserInteractionResponse]


class UserInteractionManager:
    """Coordinate one-at-a-time user interactions across the running app."""

    def __init__(self, emit_event: Callable[[events.Event], Awaitable[None]]) -> None:
        self._emit_event = emit_event
        self._pending: _PendingRequestState | None = None
        self._request_queue: asyncio.Queue[PendingUserInteractionRequest] = asyncio.Queue()

    async def request(
        self,
        *,
        request_id: str,
        session_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        tool_call_id: str | None = None,
    ) -> user_interaction.UserInteractionResponse:
        if self._pending is not None:
            raise RuntimeError("Only one user interaction can be pending at a time")

        loop = asyncio.get_running_loop()
        request = PendingUserInteractionRequest(
            request_id=request_id,
            session_id=session_id,
            source=source,
            tool_call_id=tool_call_id,
            payload=payload,
        )
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        self._pending = _PendingRequestState(request=request, future=future)

        await self._emit_event(
            events.UserInteractionRequestEvent(
                session_id=session_id,
                request_id=request_id,
                source=source,
                tool_call_id=tool_call_id,
                payload=payload,
            )
        )
        self._request_queue.put_nowait(request)

        try:
            return await future
        finally:
            pending = cast(_PendingRequestState | None, self._pending)
            if pending is not None and pending.request.request_id == request_id:
                self._pending = None

    async def wait_next_request(self) -> PendingUserInteractionRequest:
        while True:
            request = await self._request_queue.get()
            if self.is_pending(request.request_id):
                return request

    def is_pending(self, request_id: str) -> bool:
        return self._pending is not None and self._pending.request.request_id == request_id

    def respond(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        pending = self._pending
        if pending is None:
            raise ValueError("No pending user interaction")
        if pending.request.request_id != request_id:
            raise ValueError("Unknown user interaction request id")
        if pending.request.session_id != session_id:
            raise ValueError("Session mismatch for pending user interaction")
        if response.status == "submitted" and response.payload is None:
            raise ValueError("Submitted response must include payload")

        if not pending.future.done():
            pending.future.set_result(response)
        self._pending = None

    def cancel_pending(self, *, session_id: str | None = None) -> bool:
        pending = self._pending
        if pending is None:
            return False
        if session_id is not None and pending.request.session_id != session_id:
            return False
        if not pending.future.done():
            pending.future.cancel()
        self._pending = None
        return True
