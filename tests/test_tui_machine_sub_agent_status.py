from __future__ import annotations

from collections.abc import Sequence

import pytest
from rich.text import Text

from klaude_code.protocol import events, model, tools
from klaude_code.tui import machine as machine_module
from klaude_code.tui.commands import (
    AppendBashCommandOutput,
    PrintBlankLine,
    RenderBashCommandEnd,
    RenderCommand,
    RenderToolResult,
    SpinnerStatusLine,
    SpinnerUpdate,
)
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


def _right_plain(update: SpinnerUpdate) -> str:
    right = update.right_text
    if right is None:
        return ""
    plain = getattr(right, "plain", None)
    if isinstance(plain, str):
        return plain
    return str(right)


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
                sub_agent_type="finder",
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
    assert lines == ["Finding searching xxxxx | Running …"]
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
                sub_agent_type="finder",
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
    assert lines == ["Finding searching yyyyy | Bashing × 1"]

    cmds = machine.transition(
        events.ToolCallStartEvent(
            session_id=sub_session,
            tool_call_id="tc2",
            tool_name=tools.BASH,
        )
    )
    update = _last_spinner_update(cmds)
    lines = [_line_plain(line) for line in update.status_lines]
    assert lines == ["Finding searching yyyyy | Bashing × 2"]


def test_main_session_bash_tool_streams_append_only_and_keeps_success_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 0.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))

    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
        )
    )
    assert any(isinstance(cmd, AppendBashCommandOutput) for cmd in stream_cmds)
    assert not any(isinstance(cmd, RenderToolResult) for cmd in stream_cmds)

    result_cmds = machine.transition(
        events.ToolResultEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            result="hello",
            status="success",
        )
    )
    assert any(isinstance(cmd, RenderBashCommandEnd) for cmd in result_cmds)
    assert any(isinstance(cmd, RenderToolResult) for cmd in result_cmds)


def test_main_session_bash_tool_buffers_before_delay_and_falls_back_to_tool_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 3.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(
        events.ToolCallEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            arguments="{}",
            timestamp=100.0,
        )
    )

    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
            timestamp=101.0,
        )
    )
    assert stream_cmds == []

    result_cmds = machine.transition(
        events.ToolResultEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            result="hello",
            status="success",
            timestamp=102.0,
        )
    )
    assert not any(isinstance(cmd, AppendBashCommandOutput) for cmd in result_cmds)
    assert not any(isinstance(cmd, RenderBashCommandEnd) for cmd in result_cmds)
    assert any(isinstance(cmd, RenderToolResult) for cmd in result_cmds)


def test_main_session_bash_tool_flushes_buffer_after_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(machine_module, "BASH_STREAM_DELAY_SEC", 3.0)
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(
        events.ToolCallEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            arguments="{}",
            timestamp=100.0,
        )
    )

    machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="hello\n",
            timestamp=101.0,
        )
    )
    stream_cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=session_id,
            tool_call_id="bash-1",
            tool_name=tools.BASH,
            content="world\n",
            timestamp=103.5,
        )
    )
    bash_chunks = [cmd.event.content for cmd in stream_cmds if isinstance(cmd, AppendBashCommandOutput)]
    assert bash_chunks == ["hello\n", "world\n"]


def test_bash_mode_end_emits_final_tool_result_from_streamed_output() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(events.BashCommandStartEvent(session_id=session_id, command="echo hi"))
    machine.transition(events.BashCommandOutputDeltaEvent(session_id=session_id, content="hello\n"))

    end_cmds = machine.transition(events.BashCommandEndEvent(session_id=session_id, exit_code=0, cancelled=False))

    assert any(isinstance(cmd, RenderBashCommandEnd) for cmd in end_cmds)
    tool_results = [cmd for cmd in end_cmds if isinstance(cmd, RenderToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].event.tool_name == tools.BASH
    assert tool_results[0].event.result == "hello"
    assert tool_results[0].event.status == "success"
    assert any(isinstance(cmd, PrintBlankLine) for cmd in end_cmds)


def test_bash_mode_end_includes_nonzero_exit_message_in_final_tool_result() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    machine.transition(events.BashCommandStartEvent(session_id=session_id, command="false"))

    end_cmds = machine.transition(events.BashCommandEndEvent(session_id=session_id, exit_code=2, cancelled=False))

    tool_results = [cmd for cmd in end_cmds if isinstance(cmd, RenderToolResult)]
    assert len(tool_results) == 1
    assert tool_results[0].event.result == "Command exited with code 2"
    assert tool_results[0].event.status == "success"


def test_sub_agent_bash_tool_output_delta_is_ignored() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching yyyyy",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ToolOutputDeltaEvent(
            session_id=sub_session,
            tool_call_id="bash-sub-1",
            tool_name=tools.BASH,
            content="hello\n",
        )
    )

    assert cmds == []


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
                    sub_agent_type="finder",
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
    assert lines[0] == "Finding searching 0 | Running …"
    assert lines[4] == "Finding searching 4 | Running …"
    assert lines[5] == "+2 more..."


def test_sub_agent_finish_triggers_bottom_height_reset() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    start_cmds = machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="finder",
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
    assert _line_plain(update.status_lines[0]).startswith("Running Task")


def test_main_session_composing_keeps_sub_agent_activity_priority() -> None:
    machine = DisplayStateMachine()
    main_session = "main"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-task-1",
            tool_name=tools.AGENT,
        )
    )

    cmds = machine.transition(events.AssistantTextStartEvent(session_id=main_session, response_id="r1"))
    update = _last_spinner_update(cmds)

    assert len(update.status_lines) == 1
    assert _line_plain(update.status_lines[0]).startswith("Running Task")
    assert "Typing" not in _line_plain(update.status_lines[0])


def test_interrupt_clears_stale_sub_agent_status_lines() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="finder",
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
    assert "Finding" not in _line_plain(update.status_lines[0])


def test_sub_agent_non_retry_error_clears_status_lines() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )

    cmds = machine.transition(
        events.ErrorEvent(
            session_id=sub_session,
            error_message="sub-agent failed",
            can_retry=False,
        )
    )
    update = _last_spinner_update(cmds)

    assert update.reset_bottom_height is True
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Finding" not in _line_plain(update.status_lines[0])


def test_failed_agent_tool_result_clears_sub_agent_status_line() -> None:
    machine = DisplayStateMachine()
    main_session = "main"
    sub_session = "sub-1"

    machine.transition(events.TaskStartEvent(session_id=main_session, model_id="test-model"))
    machine.transition(
        events.TaskStartEvent(
            session_id=sub_session,
            sub_agent_state=model.SubAgentState(
                sub_agent_type="finder",
                sub_agent_desc="searching",
                sub_agent_prompt="prompt",
            ),
            model_id="test-model",
        )
    )
    machine.transition(
        events.ToolCallStartEvent(
            session_id=main_session,
            tool_call_id="tc-agent-1",
            tool_name=tools.AGENT,
        )
    )

    cmds = machine.transition(
        events.ToolResultEvent(
            session_id=main_session,
            tool_call_id="tc-agent-1",
            tool_name=tools.AGENT,
            result="Failed to run sub-agent",
            status="error",
            ui_extra=model.SessionIdUIExtra(session_id=sub_session),
        )
    )
    update = _last_spinner_update(cmds)

    assert update.reset_bottom_height is True
    assert update.leading_blank_line is False
    assert len(update.status_lines) == 1
    assert update.status_lines[0].session_id is None
    assert "Finding" not in _line_plain(update.status_lines[0])


def test_main_session_tokens_accumulate_across_task_boundaries() -> None:
    machine = DisplayStateMachine()
    session_id = "main"

    machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    usage_cmds = machine.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=model.Usage(
                input_tokens=30_000,
                cached_tokens=20_000,
                output_tokens=12_000,
                reasoning_tokens=2_000,
                input_cost=0.001,
                output_cost=0.002,
                cache_read_cost=0.0005,
            ),
        )
    )
    first_update = _last_spinner_update(usage_cmds)
    assert first_update.right_text is not None
    assert "in 10k · cache 20k · out 10k · thought 2k" in _right_plain(first_update)
    assert "cost $0.0035" in _right_plain(first_update)

    machine.transition(
        events.TaskFinishEvent(
            session_id=session_id,
            task_result="done",
            has_structured_output=False,
        )
    )

    restart_cmds = machine.transition(events.TaskStartEvent(session_id=session_id, model_id="test-model"))
    restart_update = _last_spinner_update(restart_cmds)
    assert restart_update.right_text is not None
    assert "in 10k · cache 20k · out 10k · thought 2k" in _right_plain(restart_update)
    assert "cost $0.0035" in _right_plain(restart_update)

    usage_cmds = machine.transition(
        events.UsageEvent(
            session_id=session_id,
            usage=model.Usage(
                input_tokens=11_000,
                cached_tokens=1_000,
                output_tokens=7_000,
                reasoning_tokens=2_000,
                input_cost=0.0003,
                output_cost=0.0007,
                cache_read_cost=0.0001,
            ),
        )
    )
    second_update = _last_spinner_update(usage_cmds)
    assert second_update.right_text is not None
    assert "in 20k · cache 21k · out 15k · thought 4k" in _right_plain(second_update)
    assert "cost $0.0046" in _right_plain(second_update)
