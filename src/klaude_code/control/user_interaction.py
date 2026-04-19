from __future__ import annotations

from dataclasses import dataclass

from klaude_code.protocol import user_interaction

__all__ = ["PendingUserInteractionRequest"]

@dataclass(frozen=True)
class PendingUserInteractionRequest:
    request_id: str
    session_id: str
    source: user_interaction.UserInteractionSource
    tool_call_id: str | None
    payload: user_interaction.UserInteractionRequestPayload
