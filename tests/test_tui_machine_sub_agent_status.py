from __future__ import annotations

from collections.abc import Sequence

from rich.text import Text

from klaude_code.protocol import events, model, tools
from klaude_code.tui.commands import RenderCommand, SpinnerStatusLine, SpinnerUpdate
from klaude_code.tui.machine import DisplayStateMachine


def _last_spinner_update(cmds: Sequence[RenderCommand]) -> SpinnerUpdate:
    for cmd in reversed(cmds):
        if isinstance(cmd, SpinnerUpdate):
            return cmd
    raise AssertionError("SpinnerUpdate not found")


def _line_plain(line: object) -> str:
    if isinstance(line, SpinnerStatusLine):
        return _line_plain(line.text)
    if isinstance(line, Text):
        return line.plain
    return str(line)


def test_sub_agent_status_lines_hide_main_reasoning() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(events.ThinkingStartEvent(session_id=main_session))

    cmds = machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching xxxxx",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    update = _last_spinner_update(cmds)

    assert _line_plain(update.status_text) == ""
    assert update.leading_blank_line is True
    assert update.status_lines[0].session_id == sub_session
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == ["Exploring searching xxxxx | Running …"]
    first_line = update.status_lines[0].text
    assert isinstance(first_line, Text)
    assert any(
        span.style == "italic" and first_line.plain[span.start : span.end] == "searching xxxxx"
        for span in first_line.spans
    )


def test_sub_agent_status_line_shows_tool_counts() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching yyyyy",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc1",
            tool_name=tools.BASH,
        )
    )
    update = _last_spinner_update(cmds)
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == ["Exploring searching yyyyy | Bashing × 1"]

    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc2",
            tool_name=tools.BASH,
        )
    )
    update = _last_spinner_update(cmds)
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == ["Exploring searching yyyyy | Bashing × 2"]


def test_sub_agent_status_lines_cap_with_more_indicator() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))

    last_update: SpinnerUpdate | None = None
    for idx in range(7):
        cmds = machine.transition(
            events.TaskStartEvent(
                session_id=f"sub-{idx}",
                sub_agent_state=model.SubAgentState(
                    sub_agent_type="Explore",
                    sub_agent_desc=f"searching {idx}",
                    sub_agent_prompt="prompt",
                ),
                model_id="test-model",
            )
        )
        last_update = _last_spinner_update(cmds)

    assert last_update is not None
    lines = [_line_plain(line) for line in last_update.status_lines]
    assert len(lines) == 6
    assert lines[0] == "Exploring searching 0 | Running …"
    assert lines[4] == "Exploring searching 4 | Running …"
    assert lines[5] == "+2 more..."


def test_sub_agent_status_line_shows_compact_metadata() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.UsageEvent(
            session_id=sub_session,
            usage=model.Usage(
                input_tokens=30_000,
                cached_tokens=20_000,
                output_tokens=12_000,
                reasoning_tokens=2_000,
                context_size=46_000,
                context_limit=300_000,
                max_tokens=100_000,
            ),
        )
    )
    update = _last_spinner_update(cmds)
    line = _line_plain(update.status_lines[0])
    assert "Exploring searching" in line
    assert "↑10k ◎20k ↓10k ∿2k" in line
    assert "46k/200k (23.0%)" in line


def test_sub_agent_metadata_is_shown_before_tool_activity() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    machine.transition(
        events.UsageEvent(
            session_id=sub_session,
            usage=model.Usage(
                input_tokens=30_000,
                cached_tokens=20_000,
                output_tokens=12_000,
                reasoning_tokens=2_000,
                context_size=46_000,
                context_limit=300_000,
                max_tokens=100_000,
            ),
        )
    )
    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc1",
            tool_name=tools.BASH,
        )
    )

    update = _last_spinner_update(cmds)
    line = _line_plain(update.status_lines[0])
    assert "46k/200k (23.0%) | Bashing × 1" in line


def test_sub_agent_finish_triggers_bottom_height_reset() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    start_cmds = machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    start_update = _last_spinner_update(start_cmds)
    assert start_update.reset_bottom_height is False

    finish_cmds = machine.transition(
        events.TaskFinishEvent(
            session_id=sub_session,
            task_result="done",
            has_structured_output=False,
        )
    )
    finish_update = _last_spinner_update(finish_cmds)
    assert finish_update.reset_bottom_height is True
    assert finish_update.leading_blank_line is False


def test_main_agent_tool_call_shows_spawning_task_before_sub_agent_starts() -> None:
    machine = DisplayStateMachine()
    main_session = "main"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-task-1",
            tool_name=tools.AGENT,
        )
    )
    update = _last_spinner_update(cmds)
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert _line_plain(update.status_lines[0]).startswith("Spawning Task")


def test_interrupt_clears_stale_sub_agent_status_lines() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="Explore",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    machine.transition(events.InterruptEvent(session_id=main_session))

    restart_cmds = machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    update = _last_spinner_update(restart_cmds)

    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Exploring" not in _line_plain(update.status_lines[0])
