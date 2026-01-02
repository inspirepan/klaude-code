import asyncio

import pytest

from klaude_code.protocol import events
from klaude_code.ui.modes.exec import display as exec_display
from klaude_code.ui.modes.exec.display import ExecDisplay


def test_exec_display_emits_osc94_only_on_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[exec_display.OSC94States] = []

    def fake_emit_osc94(state: exec_display.OSC94States, *args: object, **kwargs: object) -> None:
        calls.append(state)

    monkeypatch.setattr(exec_display, "emit_osc94", fake_emit_osc94)

    display = ExecDisplay()

    asyncio.run(display.consume_event(events.TaskStartEvent(session_id="s")))
    assert calls == []

    asyncio.run(display.consume_event(events.TaskFinishEvent(session_id="s", task_result="ok")))
    assert calls == []
    assert capsys.readouterr().out.strip() == "ok"

    asyncio.run(display.consume_event(events.ErrorEvent(error_message="boom")))
    assert calls == [exec_display.OSC94States.ERROR]
    assert capsys.readouterr().out.strip() == "Error: boom"
