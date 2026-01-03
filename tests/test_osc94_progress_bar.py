import asyncio

import pytest

from klaude_code.protocol import events
from klaude_code.ui.exec_mode import ExecDisplay


def test_exec_display_prints_result_and_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    display = ExecDisplay()

    asyncio.run(display.consume_event(events.TaskStartEvent(session_id="s")))
    assert capsys.readouterr().out.strip() == ""

    asyncio.run(display.consume_event(events.TaskFinishEvent(session_id="s", task_result="ok")))
    assert capsys.readouterr().out.strip() == "ok"

    asyncio.run(display.consume_event(events.ErrorEvent(error_message="boom", session_id="__app__")))
    assert capsys.readouterr().out.strip() == "Error: boom"
