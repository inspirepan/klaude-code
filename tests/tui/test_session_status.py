import asyncio

import pytest

from klaude_code.protocol import events
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
                assert footer.text.startswith(
                    " ◈  Needs you · running · Needs input · 3 agents · 2 shells · 1 needs attention"
                )
                assert not footer.show_spinner
            assert not any(isinstance(item, events.SessionStatusEvent) for item in display._tape.snapshot())
            await emit(events.SessionStatusEvent(session_id="main", status=SessionStatus()))
            await emit(events.RefreshDisplayEvent(session_id="main"))
            assert not updates[-1]
        finally:
            await display.stop()

    asyncio.run(scenario())
