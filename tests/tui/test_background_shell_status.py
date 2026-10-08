import asyncio
from typing import Any

import pytest

from klaude_code.protocol import events
from klaude_code.protocol.shell_task import ShellTaskSnapshot
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.display import TUIDisplay
from klaude_code.tui.input.prompt_status_bar import PromptBottomBar

from .test_transcript_rebuild import _welcome
from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def _snapshot(**changes: Any) -> ShellTaskSnapshot:
    return ShellTaskSnapshot.model_validate(
        {
            "task_id": "shell-1",
            "session_id": "main",
            "command": "sleep 60",
            "description": "Wait",
            "work_dir": "/tmp",
            "status": "running",
            "background": True,
            "started_at": 1.0,
            "output_path": "/tmp/output",
            **changes,
        }
    )


@pytest.mark.parametrize("rebuild", ["toggle", "refresh"])
def test_background_shell_status_survives_task_finish_rebuild_and_session_switch(
    monkeypatch: pytest.MonkeyPatch, rebuild: str
) -> None:
    async def _test() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []
        bar = PromptBottomBar(invalidate=lambda: None)

        def sink(lines: tuple[PromptStatusLine, ...], _separator: str | None, _reset: bool) -> None:
            updates.append(lines)
            bar.set_status_lines(lines, separator_text=_separator, reset_bottom_height=_reset)

        display = TUIDisplay(on_status_update=sink)
        display.set_progress_ui_suspended(True)

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))

        def background_line() -> PromptStatusLine | None:
            return next((line for line in updates[-1] if "Background commands" in line.text), None)

        await emit(_welcome("main"))
        tasks = [
            _snapshot(),
            _snapshot(task_id="stopping", status="stopping"),
            *(
                _snapshot(task_id=status, status=status)
                for status in ["completed", "failed", "stopped", "timed_out", "lost"]
            ),
            _snapshot(task_id="foreground", background=False),
            _snapshot(task_id="child", session_id="child"),
        ]
        full_state = events.ShellTasksUpdatedEvent(session_id="main", tasks=tasks)
        await emit(full_state)
        await emit(full_state)
        line = background_line()
        assert line is not None and "Background commands 2" in line.text
        assert "/tasks" in line.text and not line.show_spinner
        assert "Background commands 2" in "".join(fragment[1] for fragment in bar._get_status_fragments())

        control = events.ToggleTranscriptDetailEvent if rebuild == "toggle" else events.RefreshDisplayEvent
        await emit(events.TaskStartEvent(session_id="main", model_id="test-model"))
        bar.set_agent_running(True)
        await emit(events.AssistantTextStartEvent(session_id="main"))
        await emit(events.AssistantTextDeltaEvent(session_id="main", content="Working"))
        display.refresh_prompt_status()
        running_lines = updates[-1]
        assert sum("Background commands 2" in line.text for line in running_lines) == 1
        assert any(line.show_spinner for line in running_lines)
        assert "Background commands 2" in "".join(fragment[1] for fragment in bar._get_status_fragments())

        await emit(control(session_id="main"))
        display.refresh_prompt_status()
        assert sum("Background commands 2" in line.text for line in updates[-1]) == 1
        assert any(line.show_spinner for line in updates[-1])
        await emit(events.AssistantTextDeltaEvent(session_id="main", content=" more"))
        display.refresh_prompt_status()
        assert sum("Background commands 2" in line.text for line in updates[-1]) == 1
        await emit(events.AssistantTextEndEvent(session_id="main"))
        await emit(events.TaskFinishEvent(session_id="main", task_result="done"))
        bar.set_agent_running(False)
        line = background_line()
        assert line is not None and "Background commands 2" in line.text
        assert "Background commands 2" in "".join(fragment[1] for fragment in bar._get_status_fragments())

        await emit(control(session_id="main"))
        line = background_line()
        assert line is not None and "Background commands 2" in line.text

        await emit(events.ShellTasksUpdatedEvent(session_id="child", tasks=[_snapshot(session_id="child")]))
        line = background_line()
        assert line is not None and "Background commands 2" in line.text

        await emit(events.ShellTasksUpdatedEvent(session_id="main", tasks=[_snapshot(status="completed")]))
        assert background_line() is None
        await emit(full_state)
        await emit(_welcome("new"))
        assert background_line() is None
        await emit(full_state)
        assert background_line() is None
        await emit(control(session_id="new"))
        assert background_line() is None
        bar.stop()
        await display.stop()

    asyncio.run(_test())


def test_snapshot_after_empty_history_displays_idle_count(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _test() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []

        def sink(lines: tuple[PromptStatusLine, ...], _separator: str | None, _reset: bool) -> None:
            updates.append(lines)

        display = TUIDisplay(on_status_update=sink)
        display.set_progress_ui_suspended(True)
        for event in [
            _welcome("main"),
            events.ReplayHistoryEvent(session_id="main", updated_at=0.0, events=[]),
            events.ShellTasksUpdatedEvent(session_id="main", tasks=[_snapshot()]),
        ]:
            await display.consume_envelope(make_envelope(event))
        assert any("Background commands 1" in line.text for line in updates[-1])
        await display.stop()

    asyncio.run(_test())
