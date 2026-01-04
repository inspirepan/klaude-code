from __future__ import annotations

from pydantic import Field

from klaude_code.protocol import llm_param
from klaude_code.protocol.events.chat import DeveloperMessageEvent, UserMessageEvent
from klaude_code.protocol.events.lifecycle import TaskFinishEvent, TaskStartEvent, TurnStartEvent
from klaude_code.protocol.events.metadata import TaskMetadataEvent
from klaude_code.protocol.events.streaming import AssistantImageDeltaEvent, ResponseCompleteEvent
from klaude_code.protocol.events.tools import ToolCallEvent, ToolResultEvent

from .base import Event


class WelcomeEvent(Event):
    work_dir: str
    llm_config: llm_param.LLMConfigParameter
    show_klaude_code_info: bool = True
    show_sub_agent_models: bool = True
    sub_agent_models: dict[str, llm_param.LLMConfigParameter] = Field(default_factory=dict)


class ErrorEvent(Event):
    error_message: str
    can_retry: bool = False


class InterruptEvent(Event):
    pass


class EndEvent(Event):
    """Global display shutdown."""

    session_id: str = "__app__"


type ReplayEventUnion = (
    TaskStartEvent
    | TaskFinishEvent
    | TurnStartEvent
    | AssistantImageDeltaEvent
    | ResponseCompleteEvent
    | ToolCallEvent
    | ToolResultEvent
    | UserMessageEvent
    | TaskMetadataEvent
    | InterruptEvent
    | DeveloperMessageEvent
    | ErrorEvent
)


class ReplayHistoryEvent(Event):
    events: list[ReplayEventUnion]
    updated_at: float
    is_load: bool = True
