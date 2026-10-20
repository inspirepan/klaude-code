from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

type SessionStatusCategory = Literal["needs_you", "working", "idle"]


class SessionControl(BaseModel):
    paused: bool = False
    reason: str | None = None


class SessionError(BaseModel):
    code: str = "execution_failed"
    message: str


class SessionTurnResult(BaseModel):
    id: str
    result: Literal["succeeded", "failed", "interrupted"]
    reason: str | None = None


class SessionActiveTurn(BaseModel):
    id: str
    started: bool = False


class SessionRuntimeFacts(BaseModel):
    control: SessionControl = Field(default_factory=SessionControl)
    error: SessionError | None = None
    active_turn: SessionActiveTurn | None = None
    last_turn: SessionTurnResult | None = None
    completed_input_id: str | None = None
    peer_turns: int = 0


class SessionAttention(BaseModel):
    kind: Literal["needs_input", "error", "paused"]
    code: str
    source_session_id: str
    request_id: str | None = None
    message: str | None = None


class SessionContinuation(BaseModel):
    automatic: bool = False
    triggers: list[Literal["queue", "agent_result"]] = Field(default_factory=list)
    blocked_by: list[str] = Field(default_factory=list)


class SessionOwnedTasks(BaseModel):
    active_agents: int = 0
    active_shells: int = 0


class SessionStatus(BaseModel):
    category: SessionStatusCategory = "idle"
    execution: Literal["none", "queued", "running", "waiting_agents"] = "none"
    attention: list[SessionAttention] = Field(default_factory=list)
    control: SessionControl = Field(default_factory=SessionControl)
    continuation: SessionContinuation = Field(default_factory=SessionContinuation)
    last_turn: SessionTurnResult | None = None
    owned: SessionOwnedTasks = Field(default_factory=SessionOwnedTasks)
