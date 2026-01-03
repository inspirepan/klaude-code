from __future__ import annotations

import time

from pydantic import BaseModel, Field


class Event(BaseModel):
    """Base event."""

    session_id: str
    timestamp: float = Field(default_factory=time.time)


class ResponseEvent(Event):
    """Event associated with a single model response."""

    response_id: str | None = None
