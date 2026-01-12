from __future__ import annotations

from dataclasses import dataclass

from rich.console import RenderableType
from rich.text import Text

from klaude_code.protocol import events


@dataclass(frozen=True, slots=True)
class RenderCommand:
    pass


@dataclass(frozen=True, slots=True)
class RenderWelcome(RenderCommand):
    event: events.WelcomeEvent


@dataclass(frozen=True, slots=True)
class RenderUserMessage(RenderCommand):
    event: events.UserMessageEvent


@dataclass(frozen=True, slots=True)
class RenderTaskStart(RenderCommand):
    event: events.TaskStartEvent


@dataclass(frozen=True, slots=True)
class RenderDeveloperMessage(RenderCommand):
    event: events.DeveloperMessageEvent


@dataclass(frozen=True, slots=True)
class RenderCommandOutput(RenderCommand):
    event: events.CommandOutputEvent


@dataclass(frozen=True, slots=True)
class RenderBashCommandStart(RenderCommand):
    event: events.BashCommandStartEvent


@dataclass(frozen=True, slots=True)
class AppendBashCommandOutput(RenderCommand):
    event: events.BashCommandOutputDeltaEvent


@dataclass(frozen=True, slots=True)
class RenderBashCommandEnd(RenderCommand):
    event: events.BashCommandEndEvent


@dataclass(frozen=True, slots=True)
class RenderTurnStart(RenderCommand):
    event: events.TurnStartEvent


@dataclass(frozen=True, slots=True)
class RenderAssistantImage(RenderCommand):
    session_id: str
    file_path: str


@dataclass(frozen=True, slots=True)
class RenderToolCall(RenderCommand):
    event: events.ToolCallEvent


@dataclass(frozen=True, slots=True)
class RenderToolResult(RenderCommand):
    event: events.ToolResultEvent
    is_sub_agent_session: bool


@dataclass(frozen=True, slots=True)
class RenderTaskMetadata(RenderCommand):
    event: events.TaskMetadataEvent


@dataclass(frozen=True, slots=True)
class RenderTaskFinish(RenderCommand):
    event: events.TaskFinishEvent


@dataclass(frozen=True, slots=True)
class RenderInterrupt(RenderCommand):
    session_id: str


@dataclass(frozen=True, slots=True)
class RenderError(RenderCommand):
    event: events.ErrorEvent


@dataclass(frozen=True, slots=True)
class StartThinkingStream(RenderCommand):
    session_id: str


@dataclass(frozen=True, slots=True)
class AppendThinking(RenderCommand):
    session_id: str
    content: str


@dataclass(frozen=True, slots=True)
class EndThinkingStream(RenderCommand):
    session_id: str


@dataclass(frozen=True, slots=True)
class StartAssistantStream(RenderCommand):
    session_id: str


@dataclass(frozen=True, slots=True)
class AppendAssistant(RenderCommand):
    session_id: str
    content: str


@dataclass(frozen=True, slots=True)
class EndAssistantStream(RenderCommand):
    session_id: str


@dataclass(frozen=True, slots=True)
class RenderThinkingHeader(RenderCommand):
    session_id: str
    header: str


@dataclass(frozen=True, slots=True)
class SpinnerStart(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class SpinnerStop(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class SpinnerUpdate(RenderCommand):
    status_text: str | Text
    right_text: RenderableType | None


@dataclass(frozen=True, slots=True)
class PrintBlankLine(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class PrintRuleLine(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class EmitOsc94Error(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class EmitTmuxSignal(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class TaskClockStart(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class TaskClockClear(RenderCommand):
    pass


@dataclass(frozen=True, slots=True)
class RenderCompactionSummary(RenderCommand):
    summary: str
    kept_items_brief: tuple[tuple[str, int, str], ...] = ()  # (item_type, count, preview)
