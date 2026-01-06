from __future__ import annotations

from klaude_code.protocol import model

from .base import Event


class TaskStartEvent(Event):
    sub_agent_state: model.SubAgentState | None = None
    model_id: str | None = None


class TaskFinishEvent(Event):
    task_result: str
    has_structured_output: bool = False


class TurnStartEvent(Event):
    pass


class TurnEndEvent(Event):
    pass
