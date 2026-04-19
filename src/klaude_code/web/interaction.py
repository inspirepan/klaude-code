from __future__ import annotations

import asyncio
from dataclasses import dataclass

from klaude_code.app.ports import InteractionHandlerABC
from klaude_code.protocol import events, user_interaction


@dataclass
class _PendingInteraction:
    session_id: str
    future: asyncio.Future[user_interaction.UserInteractionResponse]


class WebInteractionHandler(InteractionHandlerABC):
    """Bridges runtime interaction requests and WebSocket responses."""

    def __init__(self) -> None:
        self._pending: dict[str, _PendingInteraction] = {}

    async def collect_response(
        self,
        request_event: events.UserInteractionRequestEvent,
    ) -> user_interaction.UserInteractionResponse:
        if request_event.request_id in self._pending:
            raise RuntimeError(f"Duplicate pending request id: {request_event.request_id}")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[user_interaction.UserInteractionResponse] = loop.create_future()
        self._pending[request_event.request_id] = _PendingInteraction(
            session_id=request_event.session_id,
            future=future,
        )

        try:
            return await future
        finally:
            self._pending.pop(request_event.request_id, None)

    def resolve(self, request_id: str, response: user_interaction.UserInteractionResponse) -> bool:
        pending = self._pending.get(request_id)
        if pending is None:
            return False
        if pending.future.done():
            return False
        pending.future.set_result(response)
        return True
