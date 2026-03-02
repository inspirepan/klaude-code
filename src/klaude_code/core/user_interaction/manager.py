from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

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
    """Coordinate pending user interactions across the running app."""

    def __init__(
        self,
        emit_event: Callable[[events.Event], Awaitable[None]],
        on_request_state_change: Callable[[PendingUserInteractionRequest, bool], None] | None = None,
    ) -> None:
        self._emit_event = emit_event
        self._on_request_state_change = on_request_state_change
        self._pending_requests: dict[str, _PendingRequestState] = {}
        self._request_queue: asyncio.Queue[PendingUserInteractionRequest] = asyncio.Queue()

    def set_request_state_change_callback(
        self,
        callback: Callable[[PendingUserInteractionRequest, bool], None] | None,
    ) -> None:
        self._on_request_state_change = callback

    async def request(
        self,
        *,
        request_id: str,
        session_id: str,
        source: user_interaction.UserInteractionSource,
        payload: user_interaction.UserInteractionRequestPayload,
        tool_call_id: str | None = None,
    ) -> user_interaction.UserInteractionResponse:
        if request_id in self._pending_requests:
            raise RuntimeError(f"Duplicate user interaction request id: {request_id}")

        loop = asyncio.get_running_loop()
        request = PendingUserInteractionRequest(
            request_id=request_id,
            session_id=session_id,
            source=source,
            tool_call_id=tool_call_id,
            payload=payload,
        )
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        self._pending_requests[request_id] = _PendingRequestState(request=request, future=future)
        self._notify_request_state(request=request, is_pending=True)

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
            existed = self._pending_requests.pop(request_id, None)
            if existed is not None:
                self._notify_request_state(request=existed.request, is_pending=False)

    async def wait_next_request(self) -> PendingUserInteractionRequest:
        while True:
            request = await self._request_queue.get()
            if self.is_pending(request.request_id):
                return request

    def is_pending(self, request_id: str) -> bool:
        return request_id in self._pending_requests

    def respond(
        self,
        *,
        request_id: str,
        session_id: str,
        response: user_interaction.UserInteractionResponse,
    ) -> None:
        pending = self._pending_requests.get(request_id)
        if pending is None:
            raise ValueError("No pending user interaction")
        if pending.request.session_id != session_id:
            raise ValueError("Session mismatch for pending user interaction")
        if response.status == "submitted" and response.payload is None:
            raise ValueError("Submitted response must include payload")

        if not pending.future.done():
            pending.future.set_result(response)
        self._pending_requests.pop(request_id, None)
        self._notify_request_state(request=pending.request, is_pending=False)

    def cancel_pending(self, *, session_id: str | None = None) -> bool:
        cancelled = False
        for request_id, pending in list(self._pending_requests.items()):
            if session_id is not None and pending.request.session_id != session_id:
                continue
            if not pending.future.done():
                pending.future.cancel()
            self._pending_requests.pop(request_id, None)
            self._notify_request_state(request=pending.request, is_pending=False)
            cancelled = True
        return cancelled

    def _notify_request_state(self, *, request: PendingUserInteractionRequest, is_pending: bool) -> None:
        callback = self._on_request_state_change
        if callback is None:
            return
        callback(request, is_pending)
