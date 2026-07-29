"""`/btw` status-row and panel behavior in the display state machine."""

from __future__ import annotations

import time

import pytest
from rich.cells import cell_len
from rich.text import Text

from klaude_code.const import STATUS_SIDE_QUESTION_TEXT
from klaude_code.protocol import events
from klaude_code.protocol.llm_param import LLMClientProtocol, LLMConfigParameter
from klaude_code.tui import commands as c
from klaude_code.tui import machine as machine_module
from klaude_code.tui.machine import DisplayStateMachine


def _types(cmds: list[c.RenderCommand]) -> list[str]:
    return [type(cmd).__name__ for cmd in cmds]


def _status_texts(cmds: list[c.RenderCommand]) -> list[str]:
    updates = [cmd for cmd in cmds if isinstance(cmd, c.SpinnerUpdate)]
    assert updates, "expected a SpinnerUpdate"
    lines: list[str] = []
    for line in updates[-1].status_lines:
        text = line.text
        lines.append(text.plain if isinstance(text, Text) else str(text))
    return lines


def _start_primary_task(m: DisplayStateMachine, session_id: str = "s1") -> None:
    m.transition(
        events.WelcomeEvent(
            session_id=session_id,
            work_dir="/tmp/project",
            llm_config=LLMConfigParameter(
                protocol=LLMClientProtocol.OPENAI,
                provider_name="demo",
                model_id="gpt-demo",
            ),
        )
    )
    m.transition(events.TaskStartEvent(session_id=session_id))


def _start_side_question(
    m: DisplayStateMachine, request_id: str = "r1", question: str = "why cached?"
) -> list[c.RenderCommand]:
    return m.transition(events.SideQuestionStartEvent(session_id="s1", request_id=request_id, question=question))


def test_side_question_starts_the_spinner_when_idle() -> None:
    m = DisplayStateMachine()

    cmds = _start_side_question(m)

    assert _types(cmds) == ["SpinnerStart", "SpinnerUpdate"]
    assert _status_texts(cmds) == [f"{STATUS_SIDE_QUESTION_TEXT} why cached?"]


def test_side_question_row_is_added_below_a_running_task_status() -> None:
    m = DisplayStateMachine()
    _start_primary_task(m)

    cmds = _start_side_question(m)

    # No second SpinnerStart: the task already owns the spinner.
    assert _types(cmds) == ["SpinnerUpdate"]
    lines = _status_texts(cmds)
    assert len(lines) == 2
    assert lines[-1] == f"{STATUS_SIDE_QUESTION_TEXT} why cached?"


def test_each_side_question_gets_its_own_row() -> None:
    m = DisplayStateMachine()
    _start_side_question(m, "r1", "why cached?")
    cmds = _start_side_question(m, "r2", "what is a GIL?")

    assert _status_texts(cmds) == [
        f"{STATUS_SIDE_QUESTION_TEXT} why cached?",
        f"{STATUS_SIDE_QUESTION_TEXT} what is a GIL?",
    ]


def test_long_question_is_collapsed_to_one_ellipsized_row(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_module, "_terminal_columns_cache", (time.monotonic(), 40))
    m = DisplayStateMachine()

    cmds = _start_side_question(m, "r1", "why does\nthis particular request keep missing the prompt cache?")

    (line,) = _status_texts(cmds)
    assert line.startswith(f"{STATUS_SIDE_QUESTION_TEXT} why does this")
    assert line.endswith("…")
    assert "\n" not in line
    assert cell_len(line) <= 40 - machine_module.SIDE_QUESTION_STATUS_RESERVED_CELLS


def test_answer_renders_the_panel_and_stops_the_spinner_when_idle() -> None:
    m = DisplayStateMachine()
    _start_side_question(m)

    cmds = m.transition(
        events.SideQuestionEvent(session_id="s1", request_id="r1", question="why cached?", answer="because X")
    )

    assert _types(cmds) == ["RenderSideQuestion", "SpinnerStop"]
    panel = cmds[0]
    assert isinstance(panel, c.RenderSideQuestion)
    assert panel.event.answer == "because X"


def test_failure_reports_a_notice_and_clears_the_row() -> None:
    m = DisplayStateMachine()
    _start_side_question(m)

    cmds = m.transition(
        events.SideQuestionFailedEvent(session_id="s1", request_id="r1", question="why?", error="529 overloaded")
    )

    assert _types(cmds) == ["RenderNotice", "SpinnerStop"]
    notice = cmds[0]
    assert isinstance(notice, c.RenderNotice)
    assert notice.event.is_error is True
    assert "529 overloaded" in notice.event.content


def test_task_finish_keeps_the_spinner_while_a_side_question_is_pending() -> None:
    m = DisplayStateMachine()
    _start_primary_task(m)
    _start_side_question(m)

    cmds = m.transition(events.TaskFinishEvent(session_id="s1", task_result="done"))

    assert "SpinnerStop" not in _types(cmds)
    assert _status_texts(cmds) == [f"{STATUS_SIDE_QUESTION_TEXT} why cached?"]

    cmds = m.transition(
        events.SideQuestionEvent(session_id="s1", request_id="r1", question="why cached?", answer="because X")
    )
    assert "SpinnerStop" in _types(cmds)


def test_replayed_answer_does_not_touch_the_spinner() -> None:
    """History replay has no pending row to clear, so it must not stop the spinner."""
    m = DisplayStateMachine()
    _start_primary_task(m)

    cmds = m.transition(events.SideQuestionEvent(session_id="s1", question="why cached?", answer="because X"))

    assert _types(cmds) == ["RenderSideQuestion"]
