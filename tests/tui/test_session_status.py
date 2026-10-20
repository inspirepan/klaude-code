import asyncio

import pytest

from klaude_code.protocol import events, tools
from klaude_code.protocol.models.session_status import SessionStatus
from klaude_code.tui.commands import PromptStatusLine
from klaude_code.tui.display import TUIDisplay

from .test_transcript_rebuild import _welcome
from .test_transcript_toggle import make_envelope, patch_scrollback_writes


def test_live_status_survives_history_and_transcript_rebuilds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def scenario() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []
        display = TUIDisplay(on_status_update=lambda lines, *_: updates.append(lines))
        display.set_progress_ui_suspended(True)
        current = SessionStatus.model_validate(
            {
                "category": "needs_you",
                "execution": "running",
                "owned": {"active_agents": 3, "active_shells": 2},
                "attention": [{"kind": "needs_input", "code": "tool", "source_session_id": "child"}],
            }
        )

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))

        try:
            await emit(_welcome("old"))
            # session_info arrives before the new session's welcome and history.
            await emit(events.SessionStatusEvent(session_id="main", status=current))
            await emit(_welcome("main"))
            await emit(
                events.ReplayHistoryEvent(
                    session_id="main",
                    updated_at=0,
                    events=[events.InterruptEvent(session_id="main")],
                )
            )
            for control in (events.RefreshDisplayEvent, events.ToggleTranscriptDetailEvent):
                await emit(control(session_id="main"))
                footer = updates[-1][-1]
                assert footer.text == " ◈  Needs input · 3 agents running · 2 background shells running  /tasks"
                assert not footer.show_spinner
            assert not any(isinstance(item, events.SessionStatusEvent) for item in display._tape.snapshot())
            await emit(events.SessionStatusEvent(session_id="main", status=SessionStatus()))
            await emit(events.RefreshDisplayEvent(session_id="main"))
            assert not updates[-1]
        finally:
            await display.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("execution", ["running", "queued"])
def test_status_update_preserves_standalone_compaction(monkeypatch: pytest.MonkeyPatch, execution: str) -> None:
    async def scenario() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []
        display = TUIDisplay(on_status_update=lambda lines, *_: updates.append(lines))
        display.set_progress_ui_suspended(True)

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()

        try:
            await emit(_welcome("main"))
            await emit(events.CompactionStartEvent(session_id="main", reason="manual"))
            before = updates[-1]
            assert len(before) == 1 and "ompact" in before[0].text
            await emit(
                events.SessionStatusEvent(
                    session_id="main",
                    status=SessionStatus.model_validate({"category": "working", "execution": execution}),
                )
            )
            assert updates[-1] == before
            await emit(events.RefreshDisplayEvent(session_id="main"))
            assert updates[-1] == before
            await emit(events.CompactionEndEvent(session_id="main", reason="manual"))
            if execution == "queued":
                assert [line.text for line in updates[-1]] == ["Queued"]
            else:
                assert not updates[-1]
        finally:
            await display.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("execution", "label"),
    [("queued", "Queued"), ("waiting_agents", "Waiting for agents")],
)
def test_execution_fallback_yields_to_main_activity_and_clears_on_idle(
    monkeypatch: pytest.MonkeyPatch, execution: str, label: str
) -> None:
    async def scenario() -> None:
        patch_scrollback_writes(monkeypatch)
        updates: list[tuple[PromptStatusLine, ...]] = []
        display = TUIDisplay(on_status_update=lambda lines, *_: updates.append(lines))
        display.set_progress_ui_suspended(True)
        status = SessionStatus.model_validate({"category": "working", "execution": execution})

        async def emit(event: events.Event) -> None:
            await display.consume_envelope(make_envelope(event))
            display.refresh_prompt_status()

        try:
            await emit(_welcome("main"))
            await emit(events.SessionStatusEvent(session_id="main", status=status))
            for control in (None, events.RefreshDisplayEvent, events.ToggleTranscriptDetailEvent):
                if control is not None:
                    await emit(control(session_id="main"))
                assert [line.text for line in updates[-1]] == [label]

            await emit(events.TaskStartEvent(session_id="main"))
            await emit(events.ToolCallStartEvent(session_id="main", tool_call_id="read", tool_name=tools.READ))
            await emit(events.SessionStatusEvent(session_id="main", status=status))
            assert len(updates[-1]) == 1
            assert updates[-1][0].text.startswith("Reading")

            await emit(events.TaskFinishEvent(session_id="main", task_result="done"))
            assert [line.text for line in updates[-1]] == [label]
            await emit(events.SessionStatusEvent(session_id="main", status=SessionStatus()))
            assert not updates[-1]
        finally:
            await display.stop()

    asyncio.run(scenario())
