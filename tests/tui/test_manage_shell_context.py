import asyncio
import json

import pytest

from klaude_code.protocol import events, tools
from klaude_code.protocol.models import ShellTaskUIExtra
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tui.commands import RenderToolCall
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.machine import DisplayStateMachine

from .test_transcript_rebuild import _welcome
from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def _task(session_id: str = "main") -> ShellTaskSnapshot:
    return ShellTaskSnapshot(
        task_id="0262c6ae7ded484a85620df888bf836f",
        session_id=session_id,
        command="klaude wait draft --timeout 120",
        description="Wait for draft",
        work_dir="/tmp",
        status="running",
        background=True,
        started_at=1.0,
        output_path="/tmp/draft.log",
    )


def _call() -> events.ToolCallEvent:
    return events.ToolCallEvent(
        session_id="main",
        tool_call_id="wait-draft",
        tool_name=tools.MANAGE_SHELL,
        arguments=json.dumps({"action": "wait", "task_id": _task().task_id, "wait_ms": 120000}),
    )


@pytest.mark.parametrize("source", ["snapshot", "result"])
def test_manage_shell_call_resolves_session_task_without_changing_arguments(source: str) -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome("main"))
    task = _task()
    if source == "snapshot":
        update: events.Event = events.ShellTasksUpdatedEvent(session_id="main", tasks=[task, _task("other")])
    else:
        update = events.ToolResultEvent(
            session_id="main",
            tool_call_id="list-tasks",
            tool_name=tools.MANAGE_SHELL,
            result="Task list",
            status="success",
            ui_extra=ShellTaskUIExtra(action="list", tasks=[task, _task("other")]),
        )
    machine.transition(update)
    call = _call()
    commands = machine.transition(call)
    rendered = next(command for command in commands if isinstance(command, RenderToolCall))
    assert rendered.shell_task == task
    assert rendered.event.arguments == call.arguments
    machine.transition(_welcome("other"))
    rendered = next(command for command in machine.transition(call) if isinstance(command, RenderToolCall))
    assert rendered.shell_task is None


def test_manage_shell_replay_hint_is_used_without_a_snapshot_and_rejects_foreign_tasks() -> None:
    machine = DisplayStateMachine()
    machine.transition(_welcome("main"))
    call = _call().model_copy(update={"shell_task": _task()})
    rendered = next(command for command in machine.transition(call) if isinstance(command, RenderToolCall))
    assert rendered.shell_task == _task()
    assert rendered.event.arguments == _call().arguments
    foreign = call.model_copy(update={"tool_call_id": "foreign", "shell_task": _task("other")})
    rendered = next(command for command in machine.transition(foreign) if isinstance(command, RenderToolCall))
    assert rendered.shell_task is None


@pytest.mark.parametrize("rebuild", ["toggle", "refresh"])
@pytest.mark.parametrize("source", ["live", "attach"])
def test_waiting_shell_description_is_visible_before_result_and_after_rebuild(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], rebuild: str, source: str
) -> None:
    async def run() -> None:
        writes = patch_scrollback_writes(monkeypatch)
        display = TUIDisplay()
        try:
            setup: list[events.Event] = [
                _welcome("main"),
                events.TaskStartEvent(session_id="main", model_id="test-model"),
            ]
            snapshot = events.ShellTasksUpdatedEvent(session_id="main", tasks=[_task()])
            if source == "live":
                setup.extend([snapshot, _call()])
            else:
                setup.extend([_call().model_copy(update={"shell_task": _task()}), snapshot])
            for event in setup:
                await display.consume_envelope(make_envelope(event))
            transcript = capsys.readouterr().out
            assert "Wait for draft" in transcript
            assert "0262c6ae" in transcript
            assert "120s" in transcript or "2m" in transcript
            assert "wait_ms:" not in transcript
            control = events.ToggleTranscriptDetailEvent if rebuild == "toggle" else events.RefreshDisplayEvent
            await display.consume_envelope(make_envelope(control(session_id="main")))
            assert writes[-1][1]
            assert "Wait for draft" in writes[-1][0]
        finally:
            await display.stop()

    asyncio.run(run())
