"""Background activity must not finalize the main agent's live text."""

import asyncio
import io

import pytest
from rich.console import Console

from klaude_code.protocol import events, message, tools
from klaude_code.protocol.models import TaskMetadataItem
from klaude_code.tui.commands import EndAssistantStream, EndThinkingStream
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.renderer import TUICommandRenderer
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail

from .test_async_task_transcript import _agent, _welcome


def _background_event(kind: str, session_id: str) -> events.Event:
    match kind:
        case "tool-start":
            return events.ToolCallStartEvent(session_id=session_id, tool_call_id="read", tool_name=tools.READ)
        case "tool-call":
            return events.ToolCallEvent(
                session_id=session_id, tool_call_id="read", tool_name=tools.READ, arguments='{"file_path":"README.md"}'
            )
        case "metadata":
            return events.TaskMetadataEvent(session_id=session_id, metadata=TaskMetadataItem())
        case "files":
            return events.TaskFileChangeSummaryEvent(
                session_id=session_id, summary=message.TaskFileChangeSummaryEntry()
            )
        case _:
            raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["tool-start", "tool-call", "metadata", "files"])
@pytest.mark.parametrize("thinking", [False, True])
@pytest.mark.parametrize("detail", [Detail.COMPACT, Detail.FULL])
def test_background_event_preserves_main_stream(kind: str, thinking: bool, detail: Detail) -> None:
    async def run() -> None:
        mode = TranscriptDetail()
        mode.set(detail)
        machine = DisplayStateMachine(detail=mode)
        renderer = TUICommandRenderer(detail=mode)
        output = io.StringIO()
        renderer.console = Console(file=output, width=120, theme=renderer.themes.app_theme)
        machine.transition(_welcome())
        machine.transition(
            events.BackgroundTasksUpdatedEvent(session_id="main", tasks=[_agent("a", "child", "Finder")])
        )
        start = events.ThinkingStartEvent if thinking else events.AssistantTextStartEvent
        delta = events.ThinkingDeltaEvent if thinking else events.AssistantTextDeltaEvent
        end = events.ThinkingEndEvent if thinking else events.AssistantTextEndEvent
        prefix = "已经确认部署在"
        suffix = "独立的 hillclimb-prod，API 和 worker 都在运行。"
        try:
            for event in [start(session_id="main"), delta(session_id="main", content=prefix)]:
                await renderer.execute(machine.transition(event))
            commands = machine.transition(_background_event(kind, "child"))
            assert not any(isinstance(command, (EndAssistantStream, EndThinkingStream)) for command in commands)
            await renderer.execute(commands)
            await renderer.execute(machine.transition(delta(session_id="main", content=suffix)))
            await renderer.execute(machine.transition(end(session_id="main")))
            if not thinking or detail == Detail.FULL:
                assert prefix + suffix in output.getvalue()
        finally:
            await renderer.stop()

    asyncio.run(run())


@pytest.mark.parametrize("kind", ["tool-start", "tool-call"])
def test_own_tool_still_finalizes_main_stream(kind: str) -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome())
    machine.transition(events.AssistantTextStartEvent(session_id="main"))
    commands = machine.transition(_background_event(kind, "main"))
    assert any(isinstance(command, EndAssistantStream) for command in commands)
