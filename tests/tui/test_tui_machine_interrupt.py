from __future__ import annotations

import pytest

from klaude_code.protocol import events
from klaude_code.protocol.models import SubAgentState, Usage
from klaude_code.tui.commands import (
    EndAssistantStream,
    EndThinkingStream,
    PrintBlankLine,
    RenderInterrupt,
    RenderSubAgentBatchSummary,
)
from klaude_code.tui.machine import DisplayStateMachine
from klaude_code.tui.transcript_detail import Detail, TranscriptDetail


def test_replay_interrupt_has_blank_lines_around_render() -> None:
    m = DisplayStateMachine()

    cmds = m.transition_rebuild(events.InterruptEvent(session_id="s1"))

    assert isinstance(cmds[0], EndThinkingStream)
    assert isinstance(cmds[1], EndAssistantStream)
    assert isinstance(cmds[2], RenderInterrupt)
    assert not any(isinstance(cmd, PrintBlankLine) for cmd in cmds)


def test_interrupt_without_notice_skips_render_interrupt() -> None:
    m = DisplayStateMachine()

    cmds = m.transition_rebuild(events.InterruptEvent(session_id="s1", show_notice=False))

    assert isinstance(cmds[0], EndThinkingStream)
    assert isinstance(cmds[1], EndAssistantStream)
    assert not any(isinstance(cmd, RenderInterrupt) for cmd in cmds)


@pytest.mark.parametrize("detail", list(Detail))
@pytest.mark.parametrize("is_sub_agent", [False, True])
@pytest.mark.parametrize("rebuild", [False, True])
def test_interrupt_notice_respects_session_detail_and_preserves_cancelled_summary(
    detail: Detail, is_sub_agent: bool, rebuild: bool
) -> None:
    machine = DisplayStateMachine(detail=TranscriptDetail(detail))
    transition = machine.transition_rebuild if rebuild else machine.transition
    transition(events.TaskStartEvent(session_id="main"))
    transition(
        events.TaskStartEvent(
            session_id="child",
            parent_session_id="main",
            sub_agent_state=SubAgentState(
                sub_agent_type="code-reviewer", sub_agent_desc="review changes", sub_agent_prompt="review"
            ),
        )
    )
    session_id = "child" if is_sub_agent else "main"

    commands = transition(events.InterruptEvent(session_id=session_id))

    assert any(isinstance(command, RenderInterrupt) for command in commands) == (
        not is_sub_agent or detail is Detail.FULL
    )
    assert not machine._sessions[session_id].task_active
    if is_sub_agent:
        assert machine._sessions["main"].task_active
        commands = transition(events.TaskFinishEvent(session_id="child", task_result="task cancelled"))
        if detail is Detail.COMPACT:
            summary = next(command for command in commands if isinstance(command, RenderSubAgentBatchSummary))
            assert len(summary.summaries) == 1
            assert summary.summaries[0].session_id == "child"
            assert summary.summaries[0].status == "aborted"


def test_interrupt_preserves_accumulated_usage() -> None:
    m = DisplayStateMachine()
    session_id = "s1"
    _ = m.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    _ = m.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=Usage(input_tokens=100, output_tokens=20, input_cost=0.01),
        )
    )

    _ = m.transition(events.InterruptEvent(session_id=session_id))

    assert m._spinner._token_input == 100  # pyright: ignore[reportPrivateUsage]
    assert m._spinner._token_output == 20  # pyright: ignore[reportPrivateUsage]
    assert m._spinner._cost_total == 0.01  # pyright: ignore[reportPrivateUsage]
