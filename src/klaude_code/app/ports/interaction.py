from __future__ import annotations

from abc import ABC, abstractmethod

from klaude_code.protocol import events, user_interaction


class InteractionHandlerABC(ABC):
    @abstractmethod
    async def collect_response(
        self,
        request_event: events.UserInteractionRequestEvent,
    ) -> user_interaction.UserInteractionResponse:
        pass
